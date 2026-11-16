"""Download, resume and SHA-256 check against a local HTTP server (no network, no model)."""
import hashlib
import http.server
import threading
from functools import partial

import pytest

from meorav import models


class RangeHandler(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def send_head(self):
        rng = self.headers.get("Range")
        if not rng:
            return super().send_head()
        path = self.translate_path(self.path)
        data = open(path, "rb").read()
        start = int(rng.split("=")[1].split("-")[0])
        self.send_response(206)
        self.send_header("Content-Length", str(len(data) - start))
        self.send_header("Content-Range", f"bytes {start}-{len(data) - 1}/{len(data)}")
        self.end_headers()
        import io
        return io.BytesIO(data[start:])


@pytest.fixture
def server(tmp_path):
    srv_dir = tmp_path / "srv"
    srv_dir.mkdir()
    httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), partial(RangeHandler, directory=str(srv_dir)))
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    yield srv_dir, f"http://127.0.0.1:{httpd.server_address[1]}"
    httpd.shutdown()


def _quant(srv_dir, base, payloads):
    files = []
    for role, data in payloads.items():
        name = f"{role}.gguf"
        (srv_dir / name).write_bytes(data)
        files.append({"role": role, "name": name, "url": f"{base}/{name}", "size": len(data),
                      "sha256": hashlib.sha256(data).hexdigest()})
    return {"id": "Q4_K_M", "files": files}


def test_download_resume_and_verify(server, tmp_path, monkeypatch):
    monkeypatch.setenv("MEORAV_DATA_DIR", str(tmp_path / "data"))
    srv_dir, base = server
    voice = {"id": "test-voice"}
    q = _quant(srv_dir, base, {"talker": b"T" * 3_000_000, "codec": b"C" * 500_000})
    # A half-finished talker download is resumed, not restarted.
    d = models.quant_dir(voice, q)
    d.mkdir(parents=True)
    (d / "talker.gguf.part").write_bytes(b"T" * 1_000_000)
    seen = []
    models.download(voice, q, lambda done, total, stage: seen.append((done, total)))
    assert models.is_installed(voice, q)
    assert seen[-1] == (3_500_000, 3_500_000)
    assert not list(d.glob("*.part"))


def test_bad_hash_is_deleted(server, tmp_path, monkeypatch):
    monkeypatch.setenv("MEORAV_DATA_DIR", str(tmp_path / "data"))
    srv_dir, base = server
    voice = {"id": "test-voice"}
    q = _quant(srv_dir, base, {"talker": b"x" * 1000, "codec": b"y" * 1000})
    q["files"][0]["sha256"] = "0" * 64
    with pytest.raises(ValueError, match="SHA-256 mismatch"):
        models.download(voice, q, lambda *a: None)
    assert not models.is_installed(voice, q)
    assert not (models.quant_dir(voice, q) / "talker.gguf.part").exists()


def test_reference_clips_and_local_codec_copy(server, tmp_path, monkeypatch):
    """A base model downloads its voices' reference clips; a codec already installed for another
    model (same name, size, SHA-256) is copied locally, not fetched."""
    monkeypatch.setenv("MEORAV_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setattr(models, "LOCAL_COPY_MIN", 0)
    srv_dir, base = server
    codec = b"C" * 200_000
    first = {"id": "daniel-model"}
    q1 = _quant(srv_dir, base, {"talker": b"D" * 1000, "codec": codec})
    models.download(first, q1, lambda *a: None)
    (srv_dir / "codec.gguf").unlink()  # a second fetch of the codec would now fail
    clip = b"RIFF" + b"\0" * 5000
    (srv_dir / "josh.wav").write_bytes(clip)
    multi = {"id": "multi", "mode": "base", "speakers": [
        {"id": "josh", "name": "Josh", "accent": "American male",
         "ref": {"name": "josh.wav", "url": f"{base}/josh.wav", "size": len(clip),
                 "sha256": hashlib.sha256(clip).hexdigest()}}]}
    (srv_dir / "talker.gguf").write_bytes(b"M" * 1000)
    q2 = {"id": "Q4_K_M", "files": [
        {"role": "talker", "name": "talker.gguf", "url": f"{base}/talker.gguf", "size": 1000,
         "sha256": hashlib.sha256(b"M" * 1000).hexdigest()},
        dict(q1["files"][1])]}
    assert not models.is_installed(multi, q2)
    models.download(multi, q2, lambda *a: None)
    assert models.is_installed(multi, q2)
    assert models.ref_path(multi, multi["speakers"][0]).read_bytes() == clip
    assert models.file_path(multi, q2, "codec").read_bytes() == codec


def test_repo_catalogue():
    """catalog/catalog.json: Daniel's model first (Android 0.1.0 uses voices[0]), Multi-Voice's
    five voices reachable by id, and every entry keeps the keys Android 0.1.0 requires."""
    import json
    from pathlib import Path
    cat = json.loads((Path(__file__).resolve().parents[2] / "catalog" / "catalog.json").read_text())
    assert cat["schema"] == 1
    for v in cat["voices"]:  # Catalog.kt getString/getJSONArray: missing keys reject the whole file
        assert all(k in v for k in ("id", "name", "version", "speaker", "quants"))
        for q in v["quants"]:
            assert q["id"] and q["label"] and q["files"]
            assert all(all(k in f for k in ("role", "name", "url", "size", "sha256")) for f in q["files"])
    assert cat["voices"][0]["speaker"] == "daniel"
    ms = models.models_of(cat)
    assert [m["id"] for m in ms][:1] == [cat["voices"][0]["id"]]
    for vid in ("daniel", "josh", "rivka", "nigel", "fiona", "bazza"):
        assert models.find_voice(cat, vid), vid
    m, s = models.find_voice(cat, "bazza")
    assert m.get("poc") and s["ref"]["sha256"] and s["ref"]["url"].startswith("https://cdn.hebrish.app/")


def test_load_wav_24k(tmp_path):
    import wave
    import numpy as np
    from meorav import engine
    p = tmp_path / "a.wav"
    with wave.open(str(p), "wb") as w:
        w.setnchannels(2)
        w.setsampwidth(2)
        w.setframerate(48000)
        w.writeframes(np.full(9600, 16384, dtype="<i2").tobytes())  # 0.1 s stereo
    x = engine.load_wav_24k(p)
    assert x.dtype == np.float32 and len(x) == 2400 and abs(float(x.mean()) - 0.5) < 1e-3
