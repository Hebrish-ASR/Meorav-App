"""Meorav (beta) desktop window: GTK 4 through PyGObject (python3-gi, gir1.2-gtk-4.0).

One window, same controls as the Android app: banner, voice and quant pickers, download/delete,
device picker, text box, spell-out-numbers, Speak/Stop, Play/Save WAV, About. Work runs on
background threads; every UI update goes through GLib.idle_add.
"""
from __future__ import annotations

import shutil
import subprocess
import sys
import threading
from pathlib import Path

import gi

gi.require_version("Gtk", "4.0")
from gi.repository import Gdk, Gio, GLib, Gtk  # noqa: E402

from . import __version__, core  # noqa: E402

APP_ID = "app.hebrish.meorav"
DEVICE_LABELS = [("auto", "Automatic (GPU if available)"), ("cpu", "CPU"), ("vulkan", "GPU (Vulkan)")]

CSS = b"""
.banner { background: #fff3cd; color: #5c4400; padding: 8px 12px; border-radius: 6px; }
.stats { font-family: monospace; }
"""


def ui(fn):
    """Run fn on the GTK main loop from any thread."""
    def wrap(*a, **k):
        GLib.idle_add(lambda: (fn(*a, **k), False)[1])
    return wrap


class Window(Gtk.ApplicationWindow):
    def __init__(self, app):
        super().__init__(application=app, title="Meorav (beta)")
        self.set_default_size(640, 620)
        self.engine = core.Engine()
        self.voices: list[core.Voice] = []
        self.busy = False
        self.cancel_dl = False
        self.last: core.Result | None = None
        self.player: subprocess.Popen | None = None

        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10, margin_top=12, margin_bottom=12,
                      margin_start=12, margin_end=12)
        self.set_child(box)

        banner = Gtk.Label(label=core.BANNER, wrap=True, xalign=0)
        banner.add_css_class("banner")
        box.append(banner)

        grid = Gtk.Grid(column_spacing=10, row_spacing=6)
        box.append(grid)
        self.voice_dd = Gtk.DropDown.new_from_strings([])
        self.quant_dd = Gtk.DropDown.new_from_strings([])
        self.device_dd = Gtk.DropDown.new_from_strings([l for _, l in DEVICE_LABELS])
        for row, (lbl, w) in enumerate((("Voice", self.voice_dd), ("Quality", self.quant_dd), ("Run on", self.device_dd))):
            grid.attach(Gtk.Label(label=lbl, xalign=0), 0, row, 1, 1)
            w.set_hexpand(True)
            grid.attach(w, 1, row, 1, 1)
        self.voice_dd.connect("notify::selected", lambda *_: self.on_voice_changed())
        self.quant_dd.connect("notify::selected", lambda *_: self.refresh_model())

        mrow = Gtk.Box(spacing=8)
        box.append(mrow)
        self.model_lbl = Gtk.Label(xalign=0, wrap=True, hexpand=True)
        self.dl_btn = Gtk.Button(label="Download")
        self.dl_btn.connect("clicked", lambda *_: self.on_download())
        self.del_btn = Gtk.Button(label="Delete model")
        self.del_btn.connect("clicked", lambda *_: self.on_delete())
        for w in (self.model_lbl, self.dl_btn, self.del_btn):
            mrow.append(w)
        self.progress = Gtk.ProgressBar(show_text=True, visible=False)
        box.append(self.progress)

        self.text = Gtk.TextView(wrap_mode=Gtk.WrapMode.WORD_CHAR, top_margin=6, bottom_margin=6,
                                 left_margin=6, right_margin=6)
        self.text.get_buffer().set_text(core.SAMPLE_TEXT)
        sw = Gtk.ScrolledWindow(vexpand=True, min_content_height=140)
        sw.set_child(self.text)
        frame = Gtk.Frame()
        frame.set_child(sw)
        box.append(frame)

        self.spell = Gtk.CheckButton(label="Spell out numbers (the voice was trained on numbers written as words)",
                                     active=True)
        box.append(self.spell)

        brow = Gtk.Box(spacing=8)
        box.append(brow)
        self.speak_btn = Gtk.Button(label="Speak")
        self.speak_btn.add_css_class("suggested-action")
        self.speak_btn.connect("clicked", lambda *_: self.on_speak())
        self.stop_btn = Gtk.Button(label="Stop", sensitive=False)
        self.stop_btn.connect("clicked", lambda *_: self.on_stop())
        self.play_btn = Gtk.Button(label="Play again", sensitive=False)
        self.play_btn.connect("clicked", lambda *_: self.play())
        self.save_btn = Gtk.Button(label="Save WAV…", sensitive=False)
        self.save_btn.connect("clicked", lambda *_: self.on_save())
        about = Gtk.Button(label="About")
        about.connect("clicked", lambda *_: self.on_about())
        for w in (self.speak_btn, self.stop_btn, self.play_btn, self.save_btn):
            brow.append(w)
        spacer = Gtk.Box(hexpand=True)
        brow.append(spacer)
        brow.append(about)

        self.status = Gtk.Label(xalign=0, wrap=True, selectable=True)
        self.status.add_css_class("stats")
        box.append(self.status)

        self.status.set_text("Loading the model catalogue…")
        threading.Thread(target=self.load_catalog, daemon=True).start()

    # ------------------------------------------------------------ catalogue and model state
    def load_catalog(self):
        try:
            voices, src = core.load_catalog()
        except Exception as e:  # noqa: BLE001
            self.set_status(f"No model catalogue: {e}")
            return
        self.got_catalog(voices, src)

    @ui
    def got_catalog(self, voices, src):
        self.voices = voices
        self.voice_dd.set_model(Gtk.StringList.new([v.name for v in voices]))
        self.voice_dd.set_selected(0)
        self.voice_dd.set_sensitive(len(voices) > 1)
        self.on_voice_changed()
        self.status.set_text("" if src == "remote" else f"Offline: using the {src} model catalogue.")

    def voice(self) -> core.Voice | None:
        i = self.voice_dd.get_selected()
        return self.voices[i] if self.voices and i < len(self.voices) else None

    def quant(self) -> core.Quant | None:
        v = self.voice()
        i = self.quant_dd.get_selected()
        return v.quants[i] if v and i < len(v.quants) else None

    def on_voice_changed(self):
        v = self.voice()
        if not v:
            return
        self.quant_dd.set_model(Gtk.StringList.new([q.label for q in v.quants]))
        self.quant_dd.set_selected(next((i for i, q in enumerate(v.quants) if q.default), 0))
        self.refresh_model()

    def refresh_model(self):
        v, q = self.voice(), self.quant()
        if not q:
            return
        ready = core.is_ready(v, q)
        rem = core.remaining_bytes(v, q)
        if ready:
            self.model_lbl.set_text(f"{v.name} {q.id}: downloaded ({core.human(q.total_bytes)}). {q.note}")
        else:
            partial = " (partly downloaded)" if rem < q.total_bytes else ""
            self.model_lbl.set_text(f"{v.name} {q.id}: not downloaded, {core.human(rem)} to fetch{partial}. {q.note}")
        self.dl_btn.set_label("Resume download" if 0 < rem < q.total_bytes else "Download")
        self.dl_btn.set_visible(not ready)
        self.del_btn.set_visible(ready or rem < q.total_bytes)
        self.update_buttons()

    def update_buttons(self):
        v, q = self.voice(), self.quant()
        ready = bool(q and core.is_ready(v, q))
        self.speak_btn.set_sensitive(ready and not self.busy)
        self.stop_btn.set_sensitive(self.busy)
        for w in (self.voice_dd, self.quant_dd, self.device_dd, self.dl_btn, self.del_btn):
            w.set_sensitive(not self.busy and (w is not self.voice_dd or len(self.voices) > 1))
        self.play_btn.set_sensitive(self.last is not None and not self.busy)
        self.save_btn.set_sensitive(self.last is not None and not self.busy)

    @ui
    def set_status(self, s):
        self.status.set_text(s)

    # ------------------------------------------------------------ download / delete
    def on_download(self):
        v, q = self.voice(), self.quant()
        self.busy, self.cancel_dl = True, False
        self.progress.set_visible(True)
        self.progress.set_fraction(0)
        self.update_buttons()
        self.set_status(f"Downloading {core.human(core.remaining_bytes(v, q))} from cdn.hebrish.app … "
                        "(press Stop to pause; it resumes later)")

        @ui
        def prog(done, total, name):
            self.progress.set_fraction(done / total)
            self.progress.set_text(f"{core.human(done)} / {core.human(total)}  {name}")

        def work():
            try:
                core.download(v, q, prog, lambda: self.cancel_dl)
                msg = "Downloaded and verified (SHA-256)."
            except core.Cancelled:
                msg = "Download paused. Press Resume download to continue."
            except Exception as e:  # noqa: BLE001
                msg = f"Download failed: {e}"
            self.dl_done(msg)
        threading.Thread(target=work, daemon=True).start()

    @ui
    def dl_done(self, msg):
        self.busy = False
        self.progress.set_visible(False)
        self.status.set_text(msg)
        self.refresh_model()

    def on_delete(self):
        v, q = self.voice(), self.quant()
        core.delete(v, q)
        self.status.set_text(f"Deleted {v.name} {q.id} from {core.voice_dir(v)}.")
        self.refresh_model()

    # ------------------------------------------------------------ speak
    def on_speak(self):
        buf = self.text.get_buffer()
        text = buf.get_text(buf.get_start_iter(), buf.get_end_iter(), False).strip()
        if not text:
            self.status.set_text("Type something first.")
            return
        v, q = self.voice(), self.quant()
        device = DEVICE_LABELS[self.device_dd.get_selected()][0]
        self.stop_playback()
        self.busy = True
        self.update_buttons()
        self.set_status("Generating… the model loads first (a few seconds), then speech is generated. "
                        "On a CPU, expect 2 to 3 times as long as the speech itself.")

        def work():
            try:
                r = self.engine.synthesize(v, q, text, device=device, spell=self.spell.get_active())
                self.spoke(r, None)
            except core.Cancelled:
                self.spoke(None, "Stopped.")
            except Exception as e:  # noqa: BLE001
                self.spoke(None, f"Failed: {e}")
        threading.Thread(target=work, daemon=True).start()

    @ui
    def spoke(self, r, err):
        self.busy = False
        if r:
            if self.last and self.last.wav != r.wav:
                self.last.wav.unlink(missing_ok=True)
            self.last = r
            self.status.set_text(f"{r.audio_sec:.1f} s of speech in {r.gen_sec:.1f} s "
                                 f"({r.rtf:.2f}× real time) on {r.device}.")
            self.play()
        else:
            self.status.set_text(err)
        self.update_buttons()

    def on_stop(self):
        self.cancel_dl = True
        self.engine.stop()
        self.stop_playback()

    # ------------------------------------------------------------ playback / save
    def play(self):
        if not self.last:
            return
        self.stop_playback()
        cmd = core.player_cmd(self.last.wav)
        if not cmd:
            self.status.set_text(self.status.get_text() + " No audio player found (pw-play, paplay or aplay); "
                                 "use Save WAV.")
            return
        self.player = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    def stop_playback(self):
        if self.player and self.player.poll() is None:
            self.player.terminate()
        self.player = None

    def on_save(self):
        if not self.last:
            return
        dlg = Gtk.FileDialog(title="Save WAV", initial_name="meorav.wav")

        def done(d, res):
            try:
                f = d.save_finish(res)
            except GLib.Error:
                return
            if f and f.get_path():
                shutil.copyfile(self.last.wav, f.get_path())
                self.status.set_text(f"Saved {f.get_path()}")
        dlg.save(self, None, done)

    def on_about(self):
        v = self.voice()
        Gtk.AboutDialog(
            transient_for=self, modal=True, program_name="Meorav (beta)", version=__version__,
            logo_icon_name=APP_ID, website="https://hebrish.app/models/meorav", website_label="hebrish.app/models/meorav",
            license_type=Gtk.License.MIT_X11,
            comments=("Text to speech in Daniel Rosehill's cloned voice (Irish-accented English with Hebrew "
                      "words), generated on this computer. Experimental public test build.\n\n"
                      f"Voice: {v.name if v else 'Meorav'} ({v.hf_repo if v else 'Hebrish/Meorav-GGUF'}). "
                      "The voice model is for non-commercial use only, under the Hebrish terms: "
                      f"{core.TERMS_URL}. The app code is MIT.\n\n"
                      "Engine: qwentts.cpp by ServeurpersoCom (MIT), on ggml.\n"
                      f"Models are stored in {core.data_dir() / 'models'}."),
        ).present()


class App(Gtk.Application):
    def __init__(self):
        super().__init__(application_id=APP_ID, flags=Gio.ApplicationFlags.DEFAULT_FLAGS)

    def do_activate(self):
        win = self.props.active_window
        if not win:
            prov = Gtk.CssProvider()
            prov.load_from_data(CSS)
            Gtk.StyleContext.add_provider_for_display(Gdk.Display.get_default(), prov,
                                                      Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
            win = Window(self)
            win.connect("close-request", lambda *_: (win.engine.stop(), win.stop_playback(), False)[2])
        win.present()


def main() -> int:
    return App().run(sys.argv)


if __name__ == "__main__":
    sys.exit(main())
