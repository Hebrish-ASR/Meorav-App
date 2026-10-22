package app.hebrish.meorav

import android.content.Context
import android.os.SystemClock
import java.util.concurrent.Executors
import java.util.concurrent.atomic.AtomicBoolean

/**
 * App-wide state and the one worker thread that downloads, loads and synthesises. The model stays
 * loaded until the quant changes or the files are deleted. The activity polls [state]; nothing
 * here touches views.
 */
object Engine {
    sealed class State {
        object Idle : State()
        data class Downloading(val done: Long, val total: Long) : State()
        object Loading : State()
        data class Speaking(val audioSec: Float, val elapsedSec: Float) : State()
        data class Error(val message: String) : State()
    }

    data class Result(val samples: FloatArray, val genSec: Double, val audioSec: Double, val loadSec: Double?, val quant: String) {
        val rtf: Double get() = genSec / audioSec
    }

    @Volatile var state: State = State.Idle; private set
    @Volatile var last: Result? = null; private set
    @Volatile var loadedQuant: String? = null; private set

    private val worker = Executors.newSingleThreadExecutor { r -> Thread(r, "meorav-worker").apply { priority = Thread.MAX_PRIORITY } }
    private val cancelDownload = AtomicBoolean(false)
    private var handle = 0L
    private var loadedKey: String? = null

    val busy get() = state is State.Downloading || state is State.Loading || state is State.Speaking

    fun download(ctx: Context, voice: Voice, q: Quant) {
        if (busy) return
        cancelDownload.set(false)
        state = State.Downloading(q.totalBytes - ModelStore.remaining(ctx, voice, q), q.totalBytes)
        worker.execute {
            state = try {
                ModelStore.download(ctx, voice, q, { cancelDownload.get() }) { d, t -> state = State.Downloading(d, t) }
                State.Idle
            } catch (e: ModelStore.Cancelled) {
                State.Idle
            } catch (e: Exception) {
                State.Error("Download stopped: ${e.message}")
            }
        }
    }

    fun cancel() {
        cancelDownload.set(true)
        if (state is State.Speaking) Native.cancel()
    }

    /** Free the model if it belongs to this voice/quant (before deleting its files). */
    fun unload(voice: Voice, q: Quant) {
        worker.execute {
            if (loadedKey == "${voice.id}/${q.id}") { Native.free(handle); handle = 0; loadedKey = null; loadedQuant = null }
        }
    }

    fun speak(ctx: Context, voice: Voice, q: Quant, text: String, onDone: (Result?) -> Unit) {
        if (busy) return
        state = State.Loading
        worker.execute {
            var loadSec: Double? = null
            val key = "${voice.id}/${q.id}"
            if (loadedKey != key) {
                if (handle != 0L) { Native.free(handle); handle = 0; loadedKey = null; loadedQuant = null }
                val t0 = SystemClock.elapsedRealtime()
                handle = Native.init(
                    ModelStore.path(ctx, voice, q.file("talker")).path,
                    ModelStore.path(ctx, voice, q.file("codec")).path,
                    CODEC_CHUNK_SEC)
                if (handle == 0L) { state = State.Error("Could not load the model: ${Native.lastError()}"); onDone(null); return@execute }
                loadSec = (SystemClock.elapsedRealtime() - t0) / 1000.0
                loadedKey = key; loadedQuant = q.id
            }
            val t1 = SystemClock.elapsedRealtime()
            state = State.Speaking(0f, 0f)
            val running = AtomicBoolean(true)
            val ticker = Thread {
                while (running.get()) {
                    state = State.Speaking(Native.progressFrames() / Native.FRAMES_PER_SEC, (SystemClock.elapsedRealtime() - t1) / 1000f)
                    try { Thread.sleep(250) } catch (_: InterruptedException) { break }
                }
            }.apply { start() }
            val pcm = Native.synthesize(handle, text, voice.lang, voice.speaker, -1)
            val genSec = (SystemClock.elapsedRealtime() - t1) / 1000.0
            running.set(false); ticker.interrupt(); ticker.join()
            val result = pcm?.takeIf { it.isNotEmpty() }?.let { Result(it, genSec, it.size.toDouble() / Native.SAMPLE_RATE, loadSec, q.id) }
            state = if (result != null || Native.lastError().startsWith("cancelled")) State.Idle
                    else State.Error(Native.lastError().ifEmpty { "Synthesis produced no audio" })
            if (result != null) last = result
            onDone(result)
        }
    }

    fun clearError() { if (state is State.Error) state = State.Idle }

    /** Codec decode chunk: below upstream's 24 s default to bound peak memory on a phone. */
    private const val CODEC_CHUNK_SEC = 10f
}
