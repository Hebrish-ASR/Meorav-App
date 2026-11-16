"""Convert a Qwen3-TTS fine-tune on Hugging Face to qwentts.cpp GGUFs (Q4_K_M, Q8_0) on Modal and
upload them, plus the model's voices/*.wav reference clips, to the Hebrish CDN.

Same route as the Meorav v2.2 GGUFs (Hebrish/Meorav-GGUF card, "How they were made"): qwentts.cpp
at the submodule pin (5916bf7), its unmodified convert.py to F32, then its `quantize` tool. Runs on a
Modal CPU container because no model work runs on Daniel's laptop.

    MODAL_PROFILE=danielrosehill with-secrets modal run scripts/gguf_modal.py \
        --repo Hebrish/Meorav-Multi-Voice --revision 50226a5 --cdn-prefix models/meorav-multi-voice

* HF token: Modal secret `huggingface` (HF_TOKEN) in the danielrosehill workspace.
* R2: HEBRISH_CDN_R2_ACCESS_KEY_ID / _SECRET_ACCESS_KEY are read from the local environment
  (`with-secrets`, as in the r2-upload skill) and handed to the container as an ephemeral secret.
  Without them (or with --no-upload) the run converts, prints the manifest and uploads nothing.
* Upload commands and checks are the r2-upload skill's: `aws s3 cp` with
  application/octet-stream and `public, max-age=300` (fixed model folder), then `head-object`.
Prints a JSON manifest (name, size, sha256 per file) for catalog/catalog.json.
"""
from __future__ import annotations

import json
import os

import modal

QWENTTS_REV = "5916bf7"
CPU, MEM_MB = 4, 24576

image = (
    modal.Image.debian_slim(python_version="3.12")
    .apt_install("git", "cmake", "build-essential", "curl", "unzip")
    .run_commands(
        "curl -sSL https://awscli.amazonaws.com/awscli-exe-linux-x86_64.zip -o /tmp/a.zip"
        " && unzip -q /tmp/a.zip -d /tmp && /tmp/aws/install && rm -rf /tmp/a.zip /tmp/aws",
        "git clone https://github.com/ServeurpersoCom/qwentts.cpp /qt"
        f" && cd /qt && git checkout {QWENTTS_REV} && git submodule update --init --recursive",
        # quantize only (CPU backend). GGML_NATIVE off: the build machine is not the run machine.
        "cd /qt && cmake -S . -B build -DCMAKE_BUILD_TYPE=Release -DGGML_NATIVE=OFF -DGGML_BLAS=OFF"
        " && cmake --build build -j8 --target quantize",
    )
    .pip_install("numpy", "safetensors", "gguf", "huggingface_hub")
    .pip_install("torch", index_url="https://download.pytorch.org/whl/cpu")
)
app = modal.App("meorav-gguf", image=image)

R2_ENDPOINT = "https://81ee9810726226b99b56e4d84ffac020.r2.cloudflarestorage.com"


def _sha256(p: str) -> str:
    import hashlib
    h = hashlib.sha256()
    with open(p, "rb") as f:
        while b := f.read(8 << 20):
            h.update(b)
    return h.hexdigest()


@app.function(cpu=CPU, memory=MEM_MB, timeout=3600,
              secrets=[modal.Secret.from_name("huggingface")])
def convert(repo: str, revision: str, cdn_prefix: str, upload: bool, r2: dict) -> dict:
    import glob
    import shutil
    import subprocess
    import time
    from huggingface_hub import snapshot_download

    t0 = time.time()
    run = lambda *a, **k: subprocess.run(*a, check=True, **k)  # noqa: E731
    tok = os.environ.get("HF_TOKEN") or os.environ.get("HUGGING_FACE_HUB_TOKEN")
    src = snapshot_download(repo, revision=revision, token=tok, local_dir="/work/src")
    os.makedirs("/qt/checkpoints", exist_ok=True)
    # convert.py picks the converter from the folder name: Qwen3-TTS-12Hz-<size>-<Mode> / *Tokenizer*.
    os.symlink("/work/src/speech_tokenizer", "/qt/checkpoints/Qwen3-TTS-Tokenizer-12Hz")
    cfg = json.load(open(f"{src}/config.json"))
    mode = {"base": "Base", "custom_voice": "CustomVoice", "voice_design": "VoiceDesign"}[cfg["tts_model_type"]]
    size = {"1b7": "1.7B", "0b6": "0.6B"}[cfg["tts_model_size"]]  # config says "1b7"
    talker_dir = f"/qt/checkpoints/Qwen3-TTS-12Hz-{size}-{mode}"
    os.makedirs(talker_dir)
    for f in os.listdir(src):
        if f != "speech_tokenizer" and not f.startswith("."):
            os.symlink(f"{src}/{f}", f"{talker_dir}/{f}")
    print(f"[gguf] downloaded in {time.time() - t0:.0f} s; talker dir {talker_dir}", flush=True)
    run(["python", "convert.py"], cwd="/qt")
    print(f"[gguf] converted at {time.time() - t0:.0f} s", flush=True)
    for f32 in glob.glob("/qt/models/qwen-*-F32.gguf"):
        for q in ("Q8_0", "Q4_K_M"):
            run(["./build/quantize", f32, f32.replace("-F32.gguf", f"-{q}.gguf"), q], cwd="/qt",
                stdout=subprocess.DEVNULL)
        os.remove(f32)
    print(f"[gguf] quantized at {time.time() - t0:.0f} s", flush=True)

    import gguf
    files = []
    for p in sorted(glob.glob("/qt/models/*.gguf")):
        r = gguf.GGUFReader(p)
        meta = {}
        for k in ("qwen3-tts.model_type", "general.name"):
            fld = r.fields.get(k)
            if fld is not None:
                meta[k] = bytes(fld.parts[fld.data[0]]).decode()
        n_spk = sum(1 for t in r.tensors if t.name.startswith("spk_enc."))
        files.append({"name": os.path.basename(p), "size": os.path.getsize(p), "sha256": _sha256(p),
                      "meta": meta, "spk_enc_tensors": n_spk, "path": p})
        del r
    for p in sorted(glob.glob(f"{src}/voices/*.wav")):
        files.append({"name": f"voices/{os.path.basename(p)}", "size": os.path.getsize(p),
                      "sha256": _sha256(p), "path": p})
    talkers = [f for f in files if f["name"].startswith("qwen-talker")]
    if mode == "Base" and not all(f["spk_enc_tensors"] > 0 for f in talkers):
        raise SystemExit("[gguf] base talker without speaker-encoder tensors: x-vector cloning would fail")

    if upload:
        env = dict(os.environ, AWS_ACCESS_KEY_ID=r2["id"], AWS_SECRET_ACCESS_KEY=r2["secret"],
                   AWS_DEFAULT_REGION="auto")
        for f in files:
            key = f"{cdn_prefix}/{f['name']}"
            ctype = "audio/wav" if f["name"].endswith(".wav") else "application/octet-stream"
            run(["aws", "s3", "cp", f["path"], f"s3://hebrish-cdn/{key}", "--endpoint-url", R2_ENDPOINT,
                 "--content-type", ctype, "--cache-control", "public, max-age=300", "--only-show-errors"], env=env)
            head = subprocess.run(["aws", "s3api", "head-object", "--bucket", "hebrish-cdn", "--key", key,
                                   "--endpoint-url", R2_ENDPOINT, "--query", "ContentLength"],
                                  env=env, check=True, capture_output=True, text=True).stdout.strip()
            f["r2_size"] = int(head)
            f["url"] = f"https://cdn.hebrish.app/{key}"
            print(f"[gguf] uploaded {key} ({head} bytes)", flush=True)
    for f in files:
        f.pop("path")
    shutil.rmtree("/qt/models", ignore_errors=True)
    return {"repo": repo, "revision": revision, "qwentts": QWENTTS_REV, "mode": cfg["tts_model_type"],
            "seconds": round(time.time() - t0), "cpu": CPU, "memory_mb": MEM_MB, "files": files}


@app.local_entrypoint()
def main(repo: str = "Hebrish/Meorav-Multi-Voice", revision: str = "50226a5",
         cdn_prefix: str = "models/meorav-multi-voice", no_upload: bool = False):
    r2 = {"id": os.environ.get("HEBRISH_CDN_R2_ACCESS_KEY_ID", ""),
          "secret": os.environ.get("HEBRISH_CDN_R2_SECRET_ACCESS_KEY", "")}
    upload = not no_upload and bool(r2["id"] and r2["secret"])
    if not upload:
        print("[gguf] not uploading (no R2 credentials in the environment, or --no-upload)")
    res = convert.remote(repo, revision, cdn_prefix, upload, r2)
    print(json.dumps(res, indent=2))
