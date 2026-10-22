package app.hebrish.meorav

import android.app.Activity
import android.app.ActivityManager
import android.app.AlertDialog
import android.content.Intent
import android.net.Uri
import android.os.Bundle
import android.os.Handler
import android.os.Looper
import android.text.Html
import android.text.method.LinkMovementMethod
import android.view.View
import android.view.WindowManager
import android.widget.AdapterView
import android.widget.ArrayAdapter
import android.widget.Button
import android.widget.CheckBox
import android.widget.EditText
import android.widget.ProgressBar
import android.widget.Spinner
import android.widget.TextView
import android.widget.Toast
import java.io.File
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale

class MainActivity : Activity() {
    private val ui = Handler(Looper.getMainLooper())
    private lateinit var quantSpinner: Spinner
    private lateinit var modelStatus: TextView
    private lateinit var progress: ProgressBar
    private lateinit var download: Button
    private lateinit var delete: Button
    private lateinit var text: EditText
    private lateinit var spellNumbers: CheckBox
    private lateinit var speak: Button
    private lateinit var stop: Button
    private lateinit var status: TextView
    private lateinit var play: Button
    private lateinit var save: Button
    private lateinit var share: Button
    private lateinit var device: TextView

    private val prefs by lazy { getSharedPreferences("meorav", MODE_PRIVATE) }
    private val voice: Voice get() = Catalog.voices.first()
    private var quant: Quant? = null
    private val ramGb: Double by lazy {
        val mi = ActivityManager.MemoryInfo()
        (getSystemService(ACTIVITY_SERVICE) as ActivityManager).getMemoryInfo(mi)
        mi.totalMem / 1073741824.0
    }

    private val poll = object : Runnable {
        override fun run() { render(); ui.postDelayed(this, 300) }
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContentView(R.layout.activity_main)
        // targetSdk 35+ draws edge to edge: pad the content clear of the status and nav bars.
        findViewById<View>(R.id.root).setOnApplyWindowInsetsListener { v, insets ->
            @Suppress("DEPRECATION")
            v.setPadding(insets.systemWindowInsetLeft, insets.systemWindowInsetTop, insets.systemWindowInsetRight, insets.systemWindowInsetBottom)
            insets
        }
        quantSpinner = findViewById(R.id.quant); modelStatus = findViewById(R.id.modelStatus)
        progress = findViewById(R.id.progress); download = findViewById(R.id.download); delete = findViewById(R.id.delete)
        text = findViewById(R.id.text); spellNumbers = findViewById(R.id.spellNumbers)
        speak = findViewById(R.id.speak); stop = findViewById(R.id.stop); status = findViewById(R.id.status)
        play = findViewById(R.id.play); save = findViewById(R.id.save); share = findViewById(R.id.share)
        device = findViewById(R.id.device)

        Catalog.load(this)
        setupQuants()
        Thread { if (Catalog.refresh(this)) ui.post { setupQuants() } }.start()

        download.setOnClickListener { onDownload() }
        delete.setOnClickListener { onDelete() }
        speak.setOnClickListener { onSpeak() }
        stop.setOnClickListener { Audio.stop(); Engine.cancel() }
        play.setOnClickListener { Engine.last?.let { Audio.play(it.samples) } }
        save.setOnClickListener { onSave() }
        share.setOnClickListener { onShare() }
        findViewById<Button>(R.id.about).setOnClickListener { showAbout() }
        device.text = String.format(Locale.US, "This phone: %.1f GB RAM, %d CPU cores. Engine: qwentts.cpp %s. App %s.",
            ramGb, Runtime.getRuntime().availableProcessors(), runCatching { Native.version() }.getOrDefault("?"), BuildConfig.VERSION_NAME)
    }

    override fun onResume() { super.onResume(); ui.post(poll) }
    override fun onPause() { super.onPause(); ui.removeCallbacks(poll) }

    private fun setupQuants() {
        val qs = voice.quants
        val labels = qs.map { "${voice.name} · ${it.label} · ${Format.bytes(it.totalBytes)}" }
        quantSpinner.adapter = ArrayAdapter(this, android.R.layout.simple_spinner_dropdown_item, labels)
        val saved = prefs.getString("quant", null)
        val idx = qs.indexOfFirst { it.id == saved }.takeIf { it >= 0 } ?: qs.indexOfFirst { it.isDefault }.coerceAtLeast(0)
        quantSpinner.setSelection(idx)
        quant = qs[idx]
        quantSpinner.onItemSelectedListener = object : AdapterView.OnItemSelectedListener {
            override fun onItemSelected(p: AdapterView<*>?, v: View?, pos: Int, id: Long) {
                quant = qs[pos]; prefs.edit().putString("quant", qs[pos].id).apply(); render()
            }
            override fun onNothingSelected(p: AdapterView<*>?) {}
        }
    }

    private fun lowRam(q: Quant) = ramGb + 1.0 < q.minRamGb

    private fun render() {
        val q = quant ?: return
        val st = Engine.state
        val ready = ModelStore.isReady(this, voice, q)
        val busy = Engine.busy
        window.apply { if (busy) addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON) else clearFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON) }

        modelStatus.text = buildString {
            if (ready) append("Downloaded (${Format.bytes(q.totalBytes)}). ")
            else {
                val rem = ModelStore.remaining(this@MainActivity, voice, q)
                append("Not downloaded. Download size ${Format.bytes(q.totalBytes)}")
                if (rem in 1 until q.totalBytes) append(", ${Format.bytes(rem)} left (resumes)")
                append(". ")
            }
            append(q.note)
            if (lowRam(q)) append(" This phone has %.1f GB of RAM: it will probably run out of memory.".format(Locale.US, ramGb))
            if (Engine.loadedQuant == q.id) append(" Loaded.")
        }
        progress.visibility = if (st is Engine.State.Downloading) View.VISIBLE else View.GONE
        if (st is Engine.State.Downloading && st.total > 0) progress.progress = (st.done * 1000 / st.total).toInt()
        download.visibility = if (ready) View.GONE else View.VISIBLE
        download.isEnabled = !busy
        download.text = if (ModelStore.remaining(this, voice, q) < q.totalBytes) "Resume download" else "Download"
        delete.isEnabled = !busy && ModelStore.usedBytes(this, voice) > 0
        quantSpinner.isEnabled = !busy
        speak.isEnabled = ready && !busy
        stop.isEnabled = true
        val have = Engine.last != null && !busy
        play.isEnabled = have; save.isEnabled = have; share.isEnabled = have

        status.text = when (st) {
            is Engine.State.Downloading -> "Downloading ${Format.bytes(st.done)} of ${Format.bytes(st.total)}. Keep the app open; if it stops, tap Resume."
            Engine.State.Loading -> "Loading the model into memory (first time takes a while)…"
            is Engine.State.Speaking -> String.format(Locale.US, "Generating… %.1f s of audio in %.0f s", st.audioSec, st.elapsedSec)
            is Engine.State.Error -> st.message
            Engine.State.Idle -> Engine.last?.let { r ->
                String.format(Locale.US, "Last run (%s): %.1f s of audio generated in %.1f s. Real-time factor %.2f (%s).%s",
                    r.quant, r.audioSec, r.genSec, r.rtf,
                    if (r.rtf <= 1.0) "faster than real time" else String.format(Locale.US, "%.1fx slower than real time", r.rtf),
                    r.loadSec?.let { String.format(Locale.US, " Model load: %.1f s.", it) } ?: "")
            } ?: ""
        }
    }

    private fun onDownload() {
        val q = quant ?: return
        Engine.clearError()
        val go = { Engine.download(applicationContext, voice, q) }
        val rem = ModelStore.remaining(this, voice, q)
        AlertDialog.Builder(this)
            .setTitle("Download ${q.id}?")
            .setMessage("This downloads ${Format.bytes(rem)} from cdn.hebrish.app (Wi-Fi recommended) into the app's own storage." +
                (if (lowRam(q)) "\n\nWarning: this quality needs about ${q.minRamGb} GB of RAM; this phone has %.1f GB.".format(Locale.US, ramGb) else "") +
                "\n\nThe files are checked (SHA-256) before use. Delete them any time with \"Delete model\".")
            .setPositiveButton("Download") { _, _ -> go() }
            .setNegativeButton("Cancel", null)
            .show()
    }

    private fun onDelete() {
        val q = quant ?: return
        val others = voice.quants.filter { o -> o != q && ModelStore.remaining(this, voice, o) < o.totalBytes }
        AlertDialog.Builder(this)
            .setTitle("Delete model files?")
            .setMessage("Delete the ${q.id} files (${Format.bytes(q.totalBytes)})? You can download them again later.")
            .setPositiveButton("Delete ${q.id}") { _, _ -> Engine.unload(voice, q); ModelStore.delete(this, voice, q); render() }
            .apply {
                if (others.isNotEmpty()) setNeutralButton("Delete all") { _, _ ->
                    voice.quants.forEach { Engine.unload(voice, it); ModelStore.delete(this@MainActivity, voice, it) }; render()
                }
            }
            .setNegativeButton("Cancel", null)
            .show()
    }

    private fun onSpeak() {
        val q = quant ?: return
        var t = text.text.toString().trim()
        if (t.isEmpty()) { Toast.makeText(this, "Type something first", Toast.LENGTH_SHORT).show(); return }
        if (spellNumbers.isChecked) t = Numbers.spell(t)
        Audio.stop()
        Engine.clearError()
        Engine.speak(applicationContext, voice, q, t) { r -> if (r != null) ui.post { Audio.play(r.samples) } }
        render()
    }

    private fun wavName() = "meorav-" + SimpleDateFormat("yyyyMMdd-HHmmss", Locale.US).format(Date()) + ".wav"

    private fun onSave() {
        Engine.last ?: return
        val i = Intent(Intent.ACTION_CREATE_DOCUMENT).addCategory(Intent.CATEGORY_OPENABLE).setType("audio/wav")
            .putExtra(Intent.EXTRA_TITLE, wavName())
        @Suppress("DEPRECATION")
        startActivityForResult(i, REQ_SAVE)
    }

    @Deprecated("Deprecated in Java")
    override fun onActivityResult(requestCode: Int, resultCode: Int, data: Intent?) {
        super.onActivityResult(requestCode, resultCode, data)
        val uri: Uri = data?.data ?: return
        if (requestCode != REQ_SAVE || resultCode != RESULT_OK) return
        val r = Engine.last ?: return
        runCatching { contentResolver.openOutputStream(uri)!!.use { it.write(Audio.wavBytes(r.samples)) } }
            .onSuccess { Toast.makeText(this, "Saved", Toast.LENGTH_SHORT).show() }
            .onFailure { Toast.makeText(this, "Save failed: ${it.message}", Toast.LENGTH_LONG).show() }
    }

    private fun onShare() {
        val r = Engine.last ?: return
        val dir = ShareProvider.dir(this)
        dir.listFiles()?.forEach { it.delete() }
        val f = File(dir, wavName())
        Audio.writeWav(r.samples, f)
        val i = Intent(Intent.ACTION_SEND).setType("audio/wav").putExtra(Intent.EXTRA_STREAM, ShareProvider.uri(f))
            .addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION)
        startActivity(Intent.createChooser(i, "Share audio"))
    }

    private fun showAbout() {
        val html = """
            <p><b>Meorav (beta) ${BuildConfig.VERSION_NAME}</b>: experimental text to speech that runs entirely on your phone.
            Your text is not sent anywhere; the internet is used only to download the voice model and the model list.</p>
            <p><b>The voice is Daniel Rosehill's</b> (the Hebrish developer): Irish-accented English with Hebrew words.
            Model: ${voice.name}, a full fine-tune of Qwen3-TTS-12Hz-1.7B,
            published as <a href="https://huggingface.co/${voice.hfRepo}">${voice.hfRepo}</a> on Hugging Face.</p>
            <p><b>Non-commercial use only.</b> Using the voice is subject to the Hebrish terms of use:
            <a href="https://hebrish.app/terms">hebrish.app/terms</a>. Do not use it to impersonate anyone or to deceive.</p>
            <p>Public testing: it has not been tuned for phones yet. Generation is usually slower than real time.
            Please report problems at <a href="https://github.com/Hebrish-ASR/Meorav-App/issues">github.com/Hebrish-ASR/Meorav-App</a>.</p>
            <p>Speech engine: <a href="https://github.com/ServeurpersoCom/qwentts.cpp">qwentts.cpp</a> (MIT licence) on ggml (MIT).
            App source: MIT licence.</p>
        """.trimIndent()
        val tv = TextView(this).apply {
            @Suppress("DEPRECATION")
            text = Html.fromHtml(html)
            movementMethod = LinkMovementMethod.getInstance()
            val p = (20 * resources.displayMetrics.density).toInt(); setPadding(p, p, p, 0)
        }
        AlertDialog.Builder(this).setTitle("About Meorav").setView(tv).setPositiveButton("OK", null).show()
    }

    companion object { private const val REQ_SAVE = 1 }
}
