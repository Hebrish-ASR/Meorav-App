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
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
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
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    srv_dir, base = server
    voice = {"id": "test-voice"}
    q = _quant(srv_dir, base, {"talker": b"x" * 1000, "codec": b"y" * 1000})
    q["files"][0]["sha256"] = "0" * 64
    with pytest.raises(ValueError, match="SHA-256 mismatch"):
        models.download(voice, q, lambda *a: None)
    assert not models.is_installed(voice, q)
    assert not (models.quant_dir(voice, q) / "talker.gguf.part").exists()
