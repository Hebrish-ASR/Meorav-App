package app.hebrish.meorav

/** JNI surface of libmeorav.so (src/main/cpp/meorav_jni.cpp, over qwentts.cpp's qwen.h). */
object Native {
    init { System.loadLibrary("meorav") }

    @JvmStatic external fun version(): String
    @JvmStatic external fun lastError(): String
    /** Returns a context handle, or 0 on failure (see [lastError]). Takes seconds and ~1.5-2.5 GB. */
    @JvmStatic external fun init(talkerPath: String, codecPath: String, codecChunkSec: Float): Long
    @JvmStatic external fun free(handle: Long)
    @JvmStatic external fun speakers(handle: Long): Array<String>
    /** Mono float PCM at [SAMPLE_RATE], or null on failure or cancel. Blocking. */
    @JvmStatic external fun synthesize(handle: Long, text: String, lang: String, speaker: String, seed: Long): FloatArray?
    /** Codec frames generated so far in the running synthesis (12.5 per second of audio). */
    @JvmStatic external fun progressFrames(): Int
    @JvmStatic external fun cancel()

    const val SAMPLE_RATE = 24000
    const val FRAMES_PER_SEC = 12.5f
}
