"""Meorav desktop: catalogue, model store, number spelling and the qwentts.cpp engine.

Standard library only, so the .deb needs nothing beyond python3 (and python3-gi for the GUI).

Layout at runtime (see desktop/README.md):
  engine      /usr/lib/meorav/qwen-tts (+ libggml*.so next to it), override MEORAV_ENGINE_DIR
  catalogue   remote https://cdn.hebrish.app/models/meorav/catalog.json, cached in
              ~/.local/share/meorav/catalog.json, bundled fallback /usr/share/meorav/catalog.json
  models      ~/.local/share/meorav/models/<voice id>/<file>  (+ <file>.sha256 once verified)
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import tempfile
import time
import urllib.request
import wave
from dataclasses import dataclass, field
from pathlib import Path

from . import __version__

CATALOG_URL = "https://cdn.hebrish.app/models/meorav/catalog.json"
USER_AGENT = f"Meorav-Desktop/{__version__}"
BANNER = "Experimental — public testing. Speech is generated on your computer and can be slow."
SAMPLE_TEXT = ("Hi, this is Meorav. I'm speaking from your computer, with no internet needed. "
               "I just got my teudat zehut sorted at the misrad hapnim, so that's one thing off the list.")
TERMS_URL = "https://hebrish.app/terms"

HERE = Path(__file__).resolve().parent


def data_dir() -> Path:
    base = os.environ.get("XDG_DATA_HOME") or os.path.join(Path.home(), ".local", "share")
    d = Path(base) / "meorav"
    d.mkdir(parents=True, exist_ok=True)
    return d


def engine_path() -> Path:
    """The qwen-tts binary. ggml loads its backends (CPU variants, Vulkan) from the same dir."""
    cands = []
    if os.environ.get("MEORAV_ENGINE_DIR"):
        cands.append(Path(os.environ["MEORAV_ENGINE_DIR"]) / "qwen-tts")
    cands += [Path("/usr/lib/meorav/qwen-tts"), HERE.parent / "build" / "engine" / "qwen-tts"]
    for c in cands:
        if c.is_file() and os.access(c, os.X_OK):
            return c
    raise FileNotFoundError("qwen-tts engine not found (looked in: " + ", ".join(map(str, cands)) + ")")


# ---------------------------------------------------------------- catalogue (schema 1)

@dataclass
class ModelFile:
    role: str
    name: str
    url: str
    size: int
    sha256: str


@dataclass
class Quant:
    id: str
    label: str
    default: bool
    min_ram_gb: int
    note: str
    files: list[ModelFile]

    @property
    def total_bytes(self) -> int:
        return sum(f.size for f in self.files)

    def file(self, role: str) -> ModelFile:
        return next(f for f in self.files if f.role == role)


@dataclass
class Voice:
    id: str
    name: str
    version: str
    speaker: str
    lang: str
    description: str
    hf_repo: str
    quants: list[Quant] = field(default_factory=list)

    def quant(self, qid: str | None) -> Quant:
        if qid:
            for q in self.quants:
                if q.id.lower() == qid.lower():
                    return q
            raise KeyError(f"quant {qid!r} not in {self.id} (have: {', '.join(q.id for q in self.quants)})")
        return next((q for q in self.quants if q.default), self.quants[0])


def _parse(doc: dict) -> list[Voice]:
    if doc.get("schema") != 1:
        raise ValueError(f"unsupported catalogue schema {doc.get('schema')!r}")
    voices = []
    for v in doc["voices"]:
        quants = [Quant(q["id"], q.get("label", q["id"]), bool(q.get("default")), int(q.get("min_ram_gb", 0)),
                        q.get("note", ""), [ModelFile(f["role"], f["name"], f["url"], int(f["size"]), f["sha256"].lower())
                                            for f in q["files"]]) for q in v["quants"]]
        voices.append(Voice(v["id"], v.get("name", v["id"]), v.get("version", ""), v.get("speaker", "daniel"),
                            v.get("lang", "english"), v.get("description", ""), v.get("hf_repo", ""), quants))
    if not voices:
        raise ValueError("catalogue lists no voices")
    return voices


def bundled_catalog() -> Path:
    for c in (Path("/usr/share/meorav/catalog.json"), HERE.parent.parent / "catalog" / "catalog.json"):
        if c.is_file():
            return c
    raise FileNotFoundError("bundled catalog.json not found")


def load_catalog(refresh: bool = True, timeout: float = 8.0) -> tuple[list[Voice], str]:
    """Remote catalogue if it parses (then cached), else the cache, else the bundled copy.

    Returns (voices, source). Voices are in catalogue order; the first is the default (as on Android).
    """
    cache = data_dir() / "catalog.json"
    if refresh and not os.environ.get("MEORAV_OFFLINE"):
        try:
            req = urllib.request.Request(os.environ.get("MEORAV_CATALOG_URL", CATALOG_URL),
                                         headers={"User-Agent": USER_AGENT})
            with urllib.request.urlopen(req, timeout=timeout) as r:
                raw = r.read()
            voices = _parse(json.loads(raw))
            tmp = cache.with_suffix(".tmp")
            tmp.write_bytes(raw)
            tmp.replace(cache)
            return voices, "remote"
        except Exception:
            pass
    for src, p in (("cache", cache), ("bundled", None)):
        try:
            p = p or bundled_catalog()
            return _parse(json.loads(p.read_text())), src
        except Exception:
            continue
    raise RuntimeError("no usable catalogue (remote, cache and bundled copy all failed)")


def find_voice(voices: list[Voice], vid: str | None) -> Voice:
    if not vid:
        return voices[0]
    for v in voices:
        if vid.lower() in (v.id.lower(), v.version.lower(), v.name.lower()):
            return v
    raise KeyError(f"voice {vid!r} not in catalogue (have: {', '.join(v.id for v in voices)})")


# ---------------------------------------------------------------- model store

class Cancelled(Exception):
    pass


def voice_dir(v: Voice) -> Path:
    d = data_dir() / "models" / v.id
    d.mkdir(parents=True, exist_ok=True)
    return d


def file_path(v: Voice, f: ModelFile) -> Path:
    return voice_dir(v) / f.name


def is_file_ready(v: Voice, f: ModelFile) -> bool:
    """Ready = right size and the sidecar records the catalogue's SHA-256 (written only after a
    full hash check). The sidecar matters because the CDN folder is fixed per model and a new
    version can reuse a file name, sometimes with the same size."""
    p = file_path(v, f)
    side = p.with_name(p.name + ".sha256")
    try:
        return p.stat().st_size == f.size and side.read_text().strip() == f.sha256
    except OSError:
        return False


def is_ready(v: Voice, q: Quant) -> bool:
    return all(is_file_ready(v, f) for f in q.files)


def remaining_bytes(v: Voice, q: Quant) -> int:
    n = 0
    for f in q.files:
        if is_file_ready(v, f):
            continue
        part = file_path(v, f).with_name(f.name + ".part")
        n += f.size - min(part.stat().st_size if part.exists() else 0, f.size)
    return n


def delete(v: Voice, q: Quant) -> None:
    for f in q.files:
        p = file_path(v, f)
        for x in (p, p.with_name(p.name + ".part"), p.with_name(p.name + ".sha256")):
            x.unlink(missing_ok=True)


def download(v: Voice, q: Quant, progress=None, cancel=None) -> None:
    """Download every missing file of the pair; resumable; SHA-256 checked before the rename.

    progress(done_bytes, total_bytes, file_name) is called often; cancel() -> True stops (Cancelled).
    """
    total = q.total_bytes
    done = sum(f.size for f in q.files if is_file_ready(v, f))
    for f in q.files:
        if is_file_ready(v, f):
            continue
        p = file_path(v, f)
        part = p.with_name(f.name + ".part")
        h = hashlib.sha256()
        have = part.stat().st_size if part.exists() else 0
        if have > f.size:
            part.unlink()
            have = 0
        if have:  # re-hash what is already on disk
            with open(part, "rb") as fh:
                for chunk in iter(lambda: fh.read(1 << 20), b""):
                    h.update(chunk)
        if have < f.size:
            headers = {"User-Agent": USER_AGENT}
            if have:
                headers["Range"] = f"bytes={have}-"
            req = urllib.request.Request(f.url, headers=headers)
            with urllib.request.urlopen(req, timeout=30) as r:
                if have and r.status != 206:  # server ignored the range: start over
                    have, h = 0, hashlib.sha256()
                    part.unlink(missing_ok=True)
                with open(part, "ab") as out:
                    last = 0.0
                    while True:
                        if cancel and cancel():
                            raise Cancelled()
                        chunk = r.read(1 << 20)
                        if not chunk:
                            break
                        out.write(chunk)
                        h.update(chunk)
                        have += len(chunk)
                        now = time.monotonic()
                        if progress and now - last > 0.2:
                            progress(done + have, total, f.name)
                            last = now
        if have != f.size:
            raise IOError(f"{f.name}: got {have} bytes, expected {f.size} (interrupted? run again to resume)")
        digest = h.hexdigest()
        if digest != f.sha256:
            part.unlink(missing_ok=True)
            raise IOError(f"{f.name}: SHA-256 mismatch ({digest} != {f.sha256}); partial file removed")
        part.replace(p)
        p.with_name(p.name + ".sha256").write_text(f.sha256 + "\n")
        done += f.size
        if progress:
            progress(done, total, f.name)


# ---------------------------------------------------------------- numbers (port of Numbers.kt)

_ONES = ["zero", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine", "ten", "eleven", "twelve",
         "thirteen", "fourteen", "fifteen", "sixteen", "seventeen", "eighteen", "nineteen"]
_TENS = ["", "", "twenty", "thirty", "forty", "fifty", "sixty", "seventy", "eighty", "ninety"]
_SCALES = [("trillion", 10**12), ("billion", 10**9), ("million", 10**6), ("thousand", 1000), ("", 1)]
_NUM = re.compile(r"(?<![\w.])(\d{1,3}(?:,\d{3})+|\d+)(?:\.(\d+))?(%?)")


def _u100(n: int) -> str:
    return _ONES[n] if n < 20 else _TENS[n // 10] + (f"-{_ONES[n % 10]}" if n % 10 else "")


def _u1000(n: int) -> str:
    h, r = divmod(n, 100)
    parts = []
    if h:
        parts.append(f"{_ONES[h]} hundred")
    if r:
        parts.append(("and " if h else "") + _u100(r))
    return " ".join(parts)


def _integer(n: int) -> str:
    if n == 0:
        return "zero"
    parts = []
    for name, unit in _SCALES:
        chunk, n = divmod(n, unit)
        if chunk:
            parts.append(_u1000(chunk) + (f" {name}" if name else ""))
    return " ".join(parts)


def _year(y: int) -> str:
    hi, lo = divmod(y, 100)
    if 2000 <= y <= 2009:
        return _integer(y)
    if lo == 0:
        return f"{_u100(hi)} hundred"
    if lo < 10:
        return f"{_u100(hi)} oh {_ONES[lo]}"
    return f"{_u100(hi)} {_u100(lo)}"


def spell_numbers(text: str) -> str:
    """Digits to words: Meorav was trained on numbers written as words and reads digits poorly."""
    def rep(m: re.Match) -> str:
        ip, frac, pct = m.group(1), m.group(2) or "", m.group(3)
        d = ip.replace(",", "")
        if len(d) > 15 or (len(d) > 1 and d.startswith("0")):
            w = " ".join(_ONES[int(c)] for c in d)
        elif not frac and not pct and "," not in ip and len(d) == 4 and 1100 <= int(d) <= 2099:
            w = _year(int(d))
        else:
            w = _integer(int(d))
        if frac:
            w += " point " + " ".join(_ONES[int(c)] for c in frac)
        if pct:
            w += " percent"
        return w
    return _NUM.sub(rep, text)


# ---------------------------------------------------------------- engine

DEVICES = {"auto": None, "cpu": "CPU", "vulkan": "Vulkan0"}


@dataclass
class Result:
    wav: Path
    audio_sec: float
    gen_sec: float
    device: str
    log: str

    @property
    def rtf(self) -> float:
        return self.gen_sec / self.audio_sec if self.audio_sec else float("inf")


def wav_seconds(p: Path) -> float:
    with wave.open(str(p), "rb") as w:
        return w.getnframes() / float(w.getframerate())


def _device_used(log: str, requested: str) -> str:
    m = re.findall(r"\b(Vulkan\d+|CPU|CUDA\d+)\b", log)
    if requested != "auto":
        return DEVICES[requested]
    for name in m:
        if name.startswith("Vulkan"):
            return name
    return m[0] if m else "auto"


class Engine:
    """Runs qwen-tts once per utterance (the model loads in a few seconds from disk)."""

    def __init__(self):
        self.proc: subprocess.Popen | None = None
        self.stopped = False

    def stop(self) -> None:
        self.stopped = True
        if self.proc and self.proc.poll() is None:
            self.proc.terminate()

    def _run(self, v: Voice, q: Quant, text: str, out: Path, device: str, on_line=None) -> tuple[int, str]:
        cmd = [str(engine_path()), "--model", str(file_path(v, q.file("talker"))),
               "--codec", str(file_path(v, q.file("codec"))), "--speaker", v.speaker, "--lang", v.lang,
               "--codec-chunk-dur", "10", "-o", str(out)]
        if DEVICES[device]:
            cmd += ["--device", DEVICES[device]]
        self.proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
                                     text=True, errors="replace")
        self.proc.stdin.write(text)
        self.proc.stdin.close()
        lines = []
        for line in self.proc.stderr:
            lines.append(line)
            if on_line:
                on_line(line.rstrip("\n"))
        rc = self.proc.wait()
        return rc, "".join(lines)

    def synthesize(self, v: Voice, q: Quant, text: str, out: Path | None = None, device: str = "auto",
                   spell: bool = True, on_line=None) -> Result:
        if not is_ready(v, q):
            raise RuntimeError(f"model {v.id} {q.id} is not downloaded")
        text = (spell_numbers(text) if spell else text).strip()
        if not text:
            raise ValueError("nothing to say")
        out = Path(out) if out else Path(tempfile.mkstemp(prefix="meorav-", suffix=".wav", dir=_tmp_dir())[1])
        self.stopped = False
        t0 = time.monotonic()
        rc, log = self._run(v, q, text, out, device, on_line)
        used = device
        if rc != 0 and device == "auto" and not self.stopped:
            # A GPU driver problem should not make the app unusable: retry on the CPU.
            if on_line:
                on_line("[meorav] automatic device failed, retrying on CPU")
            t0 = time.monotonic()
            rc, log2 = self._run(v, q, text, out, "cpu", on_line)
            log, used = log + log2, "cpu"
        gen = time.monotonic() - t0
        if self.stopped:
            raise Cancelled()
        if rc != 0 or not out.exists() or out.stat().st_size <= 44:
            tail = "\n".join(log.strip().splitlines()[-8:])
            raise RuntimeError(f"qwen-tts failed (exit {rc}):\n{tail}")
        return Result(out, wav_seconds(out), gen, _device_used(log, used), log)


def _tmp_dir() -> str:
    d = Path(os.environ.get("XDG_RUNTIME_DIR") or tempfile.gettempdir()) / "meorav"
    d.mkdir(parents=True, exist_ok=True)
    return str(d)


# ---------------------------------------------------------------- playback

def player_cmd(wav: Path) -> list[str] | None:
    for exe, args in (("pw-play", []), ("paplay", []), ("aplay", ["-q"])):
        if shutil.which(exe):
            return [exe, *args, str(wav)]
    return None


def human(n: int) -> str:
    return f"{n / 1e9:.2f} GB" if n >= 1e9 else f"{n / 1e6:.0f} MB"
