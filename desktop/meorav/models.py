"""Voice catalogue and model downloads.

Same catalogue as the Android app (catalog/catalog.json, served at CATALOG_URL): voices -> quants
-> a talker + codec GGUF pair with size and SHA-256. Files go to
~/.local/share/meorav/models/<voice-id>/<quant>/; a download resumes with an HTTP Range request
and is verified by SHA-256 before it is renamed into place.
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import urllib.request
from pathlib import Path
from typing import Callable

from . import __version__

CATALOG_URL = "https://cdn.hebrish.app/models/meorav/catalog.json"
UA = f"Meorav-Desktop/{__version__}"


def data_dir() -> Path:
    base = Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local/share")
    return base / "meorav"


def config_path() -> Path:
    base = Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config")
    return base / "meorav" / "config.json"


def load_config() -> dict:
    try:
        return json.loads(config_path().read_text())
    except (OSError, ValueError):
        return {}


def save_config(cfg: dict) -> None:
    p = config_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(cfg, indent=2))


def fetch_catalog(timeout: float = 20) -> dict:
    """Fetches the catalogue and caches it; falls back to the cached copy when offline."""
    cache = data_dir() / "catalog.json"
    try:
        req = urllib.request.Request(CATALOG_URL, headers={"User-Agent": UA})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            cat = json.loads(r.read())
        cache.parent.mkdir(parents=True, exist_ok=True)
        cache.write_text(json.dumps(cat, indent=2))
        return cat
    except Exception:
        if cache.is_file():
            return json.loads(cache.read_text())
        raise


def quant_dir(voice: dict, quant: dict) -> Path:
    return data_dir() / "models" / voice["id"] / quant["id"]


def file_path(voice: dict, quant: dict, role: str) -> Path:
    f = next(f for f in quant["files"] if f["role"] == role)
    return quant_dir(voice, quant) / f["name"]


def is_installed(voice: dict, quant: dict) -> bool:
    return all((quant_dir(voice, quant) / f["name"]).is_file()
               and (quant_dir(voice, quant) / f["name"]).stat().st_size == f["size"]
               for f in quant["files"])


def total_size(quant: dict) -> int:
    return sum(f["size"] for f in quant["files"])


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
    """Downloads and verifies every file of a quant. progress(done_bytes, total_bytes, stage)."""
    d = quant_dir(voice, quant)
    d.mkdir(parents=True, exist_ok=True)
    total = total_size(quant)
    done_before = 0
    for f in quant["files"]:
        final = d / f["name"]
        if final.is_file() and final.stat().st_size == f["size"]:
            done_before += f["size"]
            progress(done_before, total, "ready")
            continue
        part = d / (f["name"] + ".part")
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
