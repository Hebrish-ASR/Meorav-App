"""The Meorav window: pick a quant, download it once, type text, Speak, play or save the WAV.

Everything slow (catalogue, download, model load, synthesis) runs on a worker QThread; the UI
polls engine progress with a timer, as the Android app does.
"""
from __future__ import annotations

import time
from pathlib import Path

from PySide6.QtCore import QObject, QThread, QTimer, Signal, Slot, Qt
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import (QApplication, QComboBox, QFileDialog, QHBoxLayout, QLabel, QMainWindow,
                               QMessageBox, QPlainTextEdit, QProgressBar, QPushButton, QVBoxLayout, QWidget)

from . import __version__, engine, models

SAMPLE = "I'm heading to the shuk before Shabbat, so let's talk after, b'ezrat Hashem."
BANNER = "Experimental: public testing. Speech is generated on your CPU and can be slower than real time."


def _mb(n: int) -> str:
    return f"{n / 1e9:.2f} GB" if n >= 1e9 else f"{n / 1e6:.0f} MB"


class Worker(QObject):
    """Runs one callable on the worker thread and reports back by signal."""
    done = Signal(object)
    failed = Signal(str)
    progress = Signal(int, int, str)

    def __init__(self, fn):
        super().__init__()
        self._fn = fn

    def run(self):
        try:
            self.done.emit(self._fn(self))
        except engine.Cancelled:
            self.failed.emit("Stopped.")
        except Exception as e:  # shown to the user, not swallowed
            self.failed.emit(f"{type(e).__name__}: {e}")


class Window(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(f"Meorav (beta) {__version__}")
        self.setWindowIcon(QIcon.fromTheme("meorav"))
        self.resize(620, 480)
        self.cfg = models.load_config()
        self.catalog: dict | None = None
        self.voice: dict | None = None
        self.engine: engine.Engine | None = None
        self.engine_key: tuple | None = None
        self.audio = None
        self.sr = 24000
        self._thread: QThread | None = None
        self._worker: Worker | None = None
        self._cancel_download = False
        self._t0 = 0.0

        banner = QLabel(BANNER)
        banner.setWordWrap(True)
        banner.setStyleSheet("background:#fff3cd;color:#664d03;padding:6px;border-radius:4px;")

        self.quant = QComboBox()
        self.quant.currentIndexChanged.connect(self._quant_changed)
        self.dl_btn = QPushButton("Download")
        self.dl_btn.clicked.connect(self._download_or_delete)
        row = QHBoxLayout()
        row.addWidget(QLabel("Voice:"))
        row.addWidget(self.quant, 1)
        row.addWidget(self.dl_btn)

        self.text = QPlainTextEdit(self.cfg.get("last_text", SAMPLE))
        self.text.setPlaceholderText("Type what Meorav should say")

        self.speak_btn = QPushButton("Speak")
        self.speak_btn.setDefault(True)
        self.speak_btn.clicked.connect(self._speak_or_stop)
        self.play_btn = QPushButton("Play")
        self.play_btn.clicked.connect(self._play)
        self.save_btn = QPushButton("Save WAV…")
        self.save_btn.clicked.connect(self._save)
        btns = QHBoxLayout()
        btns.addWidget(self.speak_btn, 2)
        btns.addWidget(self.play_btn, 1)
        btns.addWidget(self.save_btn, 1)

        self.bar = QProgressBar()
        self.bar.setTextVisible(True)
        self.bar.hide()
        self.status = QLabel("Loading the voice list…")
        self.status.setWordWrap(True)
        self.status.setTextInteractionFlags(Qt.TextSelectableByMouse)

        lay = QVBoxLayout()
        for w in (banner,):
            lay.addWidget(w)
        lay.addLayout(row)
        lay.addWidget(self.text, 1)
        lay.addLayout(btns)
        lay.addWidget(self.bar)
        lay.addWidget(self.status)
        root = QWidget()
        root.setLayout(lay)
        self.setCentralWidget(root)

        self.timer = QTimer(self)
        self.timer.setInterval(250)
        self.timer.timeout.connect(self._tick)
        self._refresh_buttons()
        self._run(lambda w: models.fetch_catalog(), self._catalog_loaded)

    # ---- worker plumbing -------------------------------------------------------------------
    def _busy(self) -> bool:
        return self._thread is not None

    def _run(self, fn, on_done, on_progress=None):
        # Signals go to bound methods of this window (a QObject on the GUI thread), so Qt queues
        # them onto the GUI thread. A lambda here would run on the worker thread.
        self._on_done, self._on_progress = on_done, on_progress
        self._thread = QThread()
        self._worker = Worker(fn)
        self._worker.moveToThread(self._thread)
        self._thread.started.connect(self._worker.run)
        self._worker.done.connect(self._worker_done)
        self._worker.failed.connect(self._worker_failed)
        self._worker.progress.connect(self._worker_progress)
        self._thread.start()
        self._refresh_buttons()

    @Slot(object)
    def _worker_done(self, r):
        self._finish(self._on_done, r)

    @Slot(str)
    def _worker_failed(self, m):
        self._finish(self._failed, m)

    @Slot(int, int, str)
    def _worker_progress(self, d, t, s):
        if self._on_progress:
            self._on_progress(d, t, s)

    def _finish(self, cb, arg):
        self._thread.quit()
        self._thread.wait()
        self._thread = self._worker = None
        self.timer.stop()
        self.bar.hide()
        if cb == self._failed:  # reset whichever action was running
            self.speak_btn.setText("Speak")
            if self.dl_btn.text() == "Cancel":
                self.dl_btn.setText("Download")
        cb(arg)
        self._refresh_buttons()

    def _failed(self, msg: str):
        self.status.setText(msg)

    # ---- catalogue and quants -------------------------------------------------------------
    def _catalog_loaded(self, cat: dict):
        self.catalog = cat
        self.voice = cat["voices"][0]
        self.quant.blockSignals(True)
        self.quant.clear()
        want = self.cfg.get("quant")
        idx = 0
        for i, q in enumerate(self.voice["quants"]):
            self.quant.addItem(f"{self.voice['name']} · {q['label']} · {_mb(models.total_size(q))}", q["id"])
            if q["id"] == want or (not want and q.get("default")):
                idx = i
        self.quant.setCurrentIndex(idx)
        self.quant.blockSignals(False)
        self._quant_changed()

    def _current_quant(self) -> dict | None:
        if not self.voice:
            return None
        qid = self.quant.currentData()
        return next((q for q in self.voice["quants"] if q["id"] == qid), None)

    def _quant_changed(self, *_):
        q = self._current_quant()
        if not q:
            return
        self.cfg["quant"] = q["id"]
        models.save_config(self.cfg)
        if models.is_installed(self.voice, q):
            self.status.setText(f"{self.voice['name']} {q['id']} is downloaded. {q.get('note', '')}")
        else:
            self.status.setText(f"Download {self.voice['name']} {q['id']} ({_mb(models.total_size(q))}) "
                                f"to start. {q.get('note', '')}")
        self._refresh_buttons()

    def _refresh_buttons(self):
        q = self._current_quant()
        installed = bool(q and models.is_installed(self.voice, q))
        busy = self._busy()
        speaking = busy and self.speak_btn.text() == "Stop"
        self.quant.setEnabled(not busy)
        self.dl_btn.setText("Cancel" if busy and self.dl_btn.text() == "Cancel" else
                            ("Delete" if installed else "Download"))
        self.dl_btn.setEnabled(q is not None and (not busy or self.dl_btn.text() == "Cancel"))
        self.speak_btn.setEnabled(installed and (not busy or speaking))
        self.play_btn.setEnabled(self.audio is not None and not busy)
        self.save_btn.setEnabled(self.audio is not None and not busy)

    def _download_or_delete(self):
        q = self._current_quant()
        if self.dl_btn.text() == "Cancel":
            self._cancel_download = True
            return
        if models.is_installed(self.voice, q):
            if QMessageBox.question(self, "Delete voice", f"Delete {q['id']} ({_mb(models.total_size(q))})?") \
                    == QMessageBox.Yes:
                if self.engine_key and self.engine_key[1] == q["id"]:
                    self.engine.close()
                    self.engine = self.engine_key = None
                models.delete(self.voice, q)
                self._quant_changed()
            return
        self._cancel_download = False
        self.bar.setRange(0, 1000)
        self.bar.setValue(0)
        self.bar.show()
        self.dl_btn.setText("Cancel")

        def job(w: Worker):
            models.download(self.voice, q, lambda d, t, s: w.progress.emit(d, t, s),
                            lambda: self._cancel_download)
            return q

        def prog(done, total, stage):
            self.bar.setValue(int(1000 * done / max(total, 1)))
            self.bar.setFormat(f"{_mb(done)} / {_mb(total)}")
            self.status.setText(stage)

        def ok(_):
            self.dl_btn.setText("Download")
            self._quant_changed()

        self._run(job, ok, prog)

    # ---- speaking -------------------------------------------------------------------------
    def _speak_or_stop(self):
        if self.speak_btn.text() == "Stop":
            if self.engine:
                self.engine.cancel()
            return
        text = " ".join(self.text.toPlainText().split())
        if not text:
            return
        self.cfg["last_text"] = self.text.toPlainText()
        models.save_config(self.cfg)
        q = self._current_quant()
        key = (self.voice["id"], q["id"])
        self.speak_btn.setText("Stop")
        self.bar.setRange(0, 0)
        self.bar.setFormat("")
        self.bar.show()
        self._t0 = time.monotonic()
        need_load = self.engine_key != key

        def job(w: Worker):
            info = {}
            if need_load:
                if self.engine:
                    self.engine.close()
                    self.engine = None
                t = time.monotonic()
                self.engine = engine.Engine(models.file_path(self.voice, q, "talker"),
                                            models.file_path(self.voice, q, "codec"))
                self.engine_key = key
                info["load"] = time.monotonic() - t
            t = time.monotonic()
            audio, sr = self.engine.synthesize(text, speaker=self.voice.get("speaker", "daniel"),
                                               lang=self.voice.get("lang", "english"))
            info["gen"] = time.monotonic() - t
            return audio, sr, info

        def ok(res):
            self.speak_btn.setText("Speak")
            self.audio, self.sr, info = res
            secs = len(self.audio) / self.sr
            load = f", model load {info['load']:.1f} s" if "load" in info else ""
            self.status.setText(f"{secs:.1f} s of speech in {info['gen']:.1f} s "
                                f"(real-time factor {info['gen'] / secs:.2f}){load}. "
                                f"CPU build {engine.cpu_level()}.")
            self._play()

        self.status.setText("Loading the voice…" if need_load else "Speaking…")
        self.timer.start()
        self._run(job, ok)

    def _tick(self):
        if self.engine and self.engine_key:
            gen = self.engine.progress_seconds()
            if gen > 0:
                self.status.setText(f"Speaking… {gen:.1f} s of audio in {time.monotonic() - self._t0:.0f} s")

    def _play(self):
        if self.audio is None:
            return
        try:
            import sounddevice as sd
            sd.stop()
            sd.play(self.audio, self.sr)
        except Exception as e:
            self.status.setText(f"Playback failed ({e}); use Save WAV.")

    def _save(self):
        default = str(Path.home() / f"meorav-{time.strftime('%Y%m%d-%H%M%S')}.wav")
        path, _ = QFileDialog.getSaveFileName(self, "Save WAV", default, "WAV audio (*.wav)")
        if path:
            engine.write_wav(path, self.audio, self.sr)
            self.status.setText(f"Saved {path}")

    def closeEvent(self, ev):
        if self.engine:
            self.engine.cancel()
        self._cancel_download = True
        if self._thread:
            self._thread.quit()
            self._thread.wait(5000)
        super().closeEvent(ev)


def run() -> int:
    import sys
    app = QApplication(sys.argv)
    app.setApplicationName("Meorav")
    app.setDesktopFileName("meorav")
    w = Window()
    w.show()
    return app.exec()
