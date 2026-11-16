"""Voice catalogue and model downloads.

Same catalogue as the Android app (catalog/catalog.json, served at CATALOG_URL). Its top-level
"voices" list is really a list of *models* (the name is kept for the Android app 0.1.0, which
reads it and uses the first entry): model -> quants -> a talker + codec GGUF pair with size and
SHA-256. A model is one of two kinds:

- built-in speaker (``"speaker": "daniel"``, qwentts model_type custom_voice): Meorav v2.2;
- reference-clip voices (``"mode": "base"`` plus a ``"speakers"`` list, each with a ``ref`` WAV,
  24 kHz mono, size and SHA-256): Meorav-Multi-Voice. Android 0.1.0 ignores these keys.

Files go to <data_dir>/models/<model-id>/<quant>/ (reference clips: <model-id>/voices/), where
data_dir is ~/.local/share/meorav on Linux and %LOCALAPPDATA%\\Meorav on Windows. A download
resumes with an HTTP Range request and is verified by SHA-256 before it is renamed into place. A
file already installed for another model with the same name, size and SHA-256 (the 12 Hz codec
is shared by every Meorav model) is copied locally instead of downloaded again.
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import sys
import urllib.request
from pathlib import Path
from typing import Callable

from . import __version__

CATALOG_URL = "https://cdn.hebrish.app/models/meorav/catalog.json"
UA = f"Meorav-Desktop/{__version__}"
LOCAL_COPY_MIN = 64 << 20  # only look for a local twin of big files (GGUFs), not of clips


def _win_base() -> Path:
    return Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local") / "Meorav"


def data_dir() -> Path:
    if os.environ.get("MEORAV_DATA_DIR"):
        return Path(os.environ["MEORAV_DATA_DIR"])
    if sys.platform == "win32":
        return _win_base()
    base = Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local/share")
    return base / "meorav"


def config_path() -> Path:
    if os.environ.get("MEORAV_DATA_DIR"):
        return Path(os.environ["MEORAV_DATA_DIR"]) / "config.json"
    if sys.platform == "win32":
        return _win_base() / "config.json"
    base = Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config")
    return base / "meorav" / "config.json"


def load_config() -> dict:
    try:
        return json.loads(config_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def save_config(cfg: dict) -> None:
    p = config_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(cfg, indent=2), encoding="utf-8")


def fetch_catalog(timeout: float = 20) -> dict:
    """Fetches the catalogue and caches it; falls back to the cached copy when offline."""
    cache = data_dir() / "catalog.json"
    src = os.environ.get("MEORAV_CATALOG")  # a local file or URL instead of CATALOG_URL (CI tests the repo's copy)
    if src and not src.startswith(("http://", "https://")):
        return json.loads(Path(src).read_text(encoding="utf-8"))
    try:
        req = urllib.request.Request(src or CATALOG_URL, headers={"User-Agent": UA})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            cat = json.loads(r.read())
        cache.parent.mkdir(parents=True, exist_ok=True)
        cache.write_text(json.dumps(cat, indent=2), encoding="utf-8")
        return cat
    except Exception:
        if cache.is_file():
            return json.loads(cache.read_text(encoding="utf-8"))
        raise


def models_of(cat: dict) -> list[dict]:
    """Catalogue entries this app can run: a built-in speaker, or base mode with speakers."""
    return [m for m in cat.get("voices", [])
            if m.get("engine", "qwentts") == "qwentts" and m.get("quants") and (m.get("speakers") if m.get("mode") == "base" else m.get("speaker"))]


def speakers_of(model: dict) -> list[dict]:
    """The voices of a model as dicts with id, name, accent (and ref for base models)."""
    if model.get("mode") == "base":
        return model["speakers"]
    return [{"id": model["speaker"], "name": model.get("speaker_name", model["speaker"].title()),
             "accent": model.get("speaker_accent", "")}]


def find_voice(cat: dict, voice_id: str) -> tuple[dict, dict] | None:
    """(model, speaker) for a voice id such as "josh" or "daniel"; the first model that has it."""
    for m in models_of(cat):
        for s in speakers_of(m):
            if s["id"] == voice_id:
                return m, s
    return None


def ref_path(model: dict, speaker: dict) -> Path:
    return data_dir() / "models" / model["id"] / "voices" / speaker["ref"]["name"]


def _ref_files(model: dict) -> list[tuple[dict, Path]]:
    return [(s["ref"], ref_path(model, s)) for s in model.get("speakers", []) if s.get("ref")]


def quant_dir(voice: dict, quant: dict) -> Path:
    return data_dir() / "models" / voice["id"] / quant["id"]


def file_path(voice: dict, quant: dict, role: str) -> Path:
    f = next(f for f in quant["files"] if f["role"] == role)
    return quant_dir(voice, quant) / f["name"]


def _ok(p: Path, size: int) -> bool:
    return p.is_file() and p.stat().st_size == size


def is_installed(voice: dict, quant: dict) -> bool:
    return all(_ok(quant_dir(voice, quant) / f["name"], f["size"]) for f in quant["files"]) \
        and all(_ok(p, f["size"]) for f, p in _ref_files(voice))


def total_size(quant: dict) -> int:
    return sum(f["size"] for f in quant["files"])


def _local_copy(f: dict, dest: Path) -> bool:
    """Copies an identical file installed for another model or quant instead of downloading it."""
    root = data_dir() / "models"
    for cand in root.glob(f"*/*/{f['name']}") if root.is_dir() else []:
        if cand != dest and _ok(cand, f["size"]) and _sha256(cand) == f["sha256"]:
            tmp = dest.with_name(dest.name + ".part")
            try:
                os.link(cand, tmp)
            except OSError:
                shutil.copyfile(cand, tmp)
            tmp.replace(dest)
            return True
    return False


def delete(voice: dict, quant: dict) -> None:
    shutil.rmtree(quant_dir(voice, quant), ignore_errors=True)


def _sha256(path: Path, progress: Callable[[int], None] | None = None) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        while chunk := fh.read(4 << 20):
            h.update(chunk)
            if progress:
                progress(len(chunk))
    return h.hexdigest()


def download(voice: dict, quant: dict, progress: Callable[[int, int, str], None],
             cancelled: Callable[[], bool] = lambda: False) -> None:
    """Downloads and verifies every file of a quant, plus the model's reference clips if it has
    any. progress(done_bytes, total_bytes, stage)."""
    d = quant_dir(voice, quant)
    d.mkdir(parents=True, exist_ok=True)
    jobs = [(f, d / f["name"]) for f in quant["files"]] + _ref_files(voice)
    total = sum(f["size"] for f, _ in jobs)
    done_before = 0
    for f, final in jobs:
        final.parent.mkdir(parents=True, exist_ok=True)
        if _ok(final, f["size"]) or (f["size"] >= LOCAL_COPY_MIN and _local_copy(f, final)):
            done_before += f["size"]
            progress(done_before, total, "ready")
            continue
        part = final.with_name(f["name"] + ".part")
        have = part.stat().st_size if part.is_file() else 0
        if have > f["size"]:
            part.unlink()
            have = 0
        if have < f["size"]:
            req = urllib.request.Request(f["url"], headers={"User-Agent": UA})
            if have:
                req.add_header("Range", f"bytes={have}-")
            with urllib.request.urlopen(req, timeout=60) as r:
                if have and r.status != 206:  # server ignored the range: start over
                    have = 0
                with open(part, "ab" if have else "wb") as out:
                    while chunk := r.read(1 << 20):
                        if cancelled():
                            raise InterruptedError("download cancelled")
                        out.write(chunk)
                        have += len(chunk)
                        progress(done_before + have, total, f"downloading {f['name']}")
        checked = 0

        def tick(n: int) -> None:
            nonlocal checked
            checked += n
            progress(done_before + checked, total, f"checking {f['name']}")

        digest = _sha256(part, tick)
        if digest != f["sha256"]:
            part.unlink(missing_ok=True)
            raise ValueError(f"{f['name']}: SHA-256 mismatch (got {digest[:12]}…); deleted, retry")
        part.rename(final)
        done_before += f["size"]
        progress(done_before, total, "ready")
