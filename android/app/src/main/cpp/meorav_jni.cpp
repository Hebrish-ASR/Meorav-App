// JNI bridge: app.hebrish.meorav.Native <-> qwentts.cpp public C API (qwen.h).
//
// One synthesis at a time (the app serialises calls on one worker thread). Progress and
// cancellation use qt_tts_params.cancel, which qwentts polls at the top of every Talker
// decode step, i.e. once per 12.5 Hz codec frame (80 ms of audio): counting the polls gives
// the seconds of audio generated so far without switching to the streaming path.
#include <jni.h>
#include <android/log.h>

#include <atomic>
#include <string>

#include "qwen.h"

#define TAG "MeoravNative"

static std::atomic<int>  g_frames{0};
static std::atomic<bool> g_cancel{false};
static std::string       g_last_error;

static void log_cb(enum qt_log_level level, const char * msg, void *) {
    int prio = level == QT_LOG_ERROR ? ANDROID_LOG_ERROR
             : level == QT_LOG_WARN  ? ANDROID_LOG_WARN
             : level == QT_LOG_INFO  ? ANDROID_LOG_INFO
                                     : ANDROID_LOG_DEBUG;
    __android_log_print(prio, TAG, "%s", msg);
}

static bool cancel_cb(void *) {
    g_frames.fetch_add(1, std::memory_order_relaxed);
    return g_cancel.load(std::memory_order_relaxed);
}

static std::string jstr(JNIEnv * env, jstring s) {
    if (!s) return {};
    const char * c = env->GetStringUTFChars(s, nullptr);
    std::string out(c ? c : "");
    if (c) env->ReleaseStringUTFChars(s, c);
    return out;
}

static void set_error(const char * prefix) {
    const char * e = qt_last_error();
    g_last_error = std::string(prefix) + (e && *e ? e : "unknown error");
    __android_log_print(ANDROID_LOG_ERROR, TAG, "%s", g_last_error.c_str());
}

extern "C" {

JNIEXPORT jstring JNICALL Java_app_hebrish_meorav_Native_version(JNIEnv * env, jclass) {
    return env->NewStringUTF(qt_version());
}

JNIEXPORT jstring JNICALL Java_app_hebrish_meorav_Native_lastError(JNIEnv * env, jclass) {
    return env->NewStringUTF(g_last_error.c_str());
}

JNIEXPORT jlong JNICALL Java_app_hebrish_meorav_Native_init(JNIEnv * env, jclass, jstring talker,
                                                            jstring codec, jfloat chunkSec) {
    qt_log_set(log_cb, nullptr);
    std::string t = jstr(env, talker), c = jstr(env, codec);
    struct qt_init_params p;
    qt_init_default_params(&p);
    p.talker_path     = t.c_str();
    p.codec_path      = c.c_str();
    // device stays NULL: only the CPU backend is compiled in, so "best" is CPU.
    p.max_batch       = 1;
    p.codec_chunk_sec = chunkSec;
    struct qt_context * q = qt_init(&p);
    if (!q) {
        set_error("load failed: ");
        return 0;
    }
    __android_log_print(ANDROID_LOG_INFO, TAG, "loaded %s, type %s, %d speakers", qt_version(),
                        qt_model_type(q), qt_n_speakers(q));
    return reinterpret_cast<jlong>(q);
}

JNIEXPORT void JNICALL Java_app_hebrish_meorav_Native_free(JNIEnv *, jclass, jlong h) {
    qt_free(reinterpret_cast<struct qt_context *>(h));
}

JNIEXPORT jobjectArray JNICALL Java_app_hebrish_meorav_Native_speakers(JNIEnv * env, jclass, jlong h) {
    auto * q = reinterpret_cast<struct qt_context *>(h);
    int    n = q ? qt_n_speakers(q) : 0;
    jobjectArray arr = env->NewObjectArray(n, env->FindClass("java/lang/String"), nullptr);
    for (int i = 0; i < n; i++) {
        env->SetObjectArrayElement(arr, i, env->NewStringUTF(qt_speaker_name(q, i)));
    }
    return arr;
}

JNIEXPORT jint JNICALL Java_app_hebrish_meorav_Native_progressFrames(JNIEnv *, jclass) {
    return g_frames.load(std::memory_order_relaxed);
}

JNIEXPORT void JNICALL Java_app_hebrish_meorav_Native_cancel(JNIEnv *, jclass) {
    g_cancel.store(true);
}

// Returns mono float PCM at 24 kHz, or null on failure / cancel (see lastError()).
JNIEXPORT jfloatArray JNICALL Java_app_hebrish_meorav_Native_synthesize(JNIEnv * env, jclass, jlong h,
                                                                       jstring text, jstring lang,
                                                                       jstring speaker, jlong seed) {
    auto * q = reinterpret_cast<struct qt_context *>(h);
    if (!q) {
        g_last_error = "model not loaded";
        return nullptr;
    }
    std::string t = jstr(env, text), l = jstr(env, lang), s = jstr(env, speaker);
    struct qt_tts_params p;
    qt_tts_default_params(&p);
    p.text    = t.c_str();
    p.lang    = l.empty() ? nullptr : l.c_str();
    p.speaker = s.empty() ? nullptr : s.c_str();
    p.seed    = seed;
    p.cancel  = cancel_cb;
    g_frames.store(0);
    g_cancel.store(false);

    struct qt_audio a = {0};
    enum qt_status  rc = qt_synthesize(q, &p, &a);
    if (rc != QT_STATUS_OK) {
        set_error(rc == QT_STATUS_CANCELLED ? "cancelled: " : "synthesis failed: ");
        qt_audio_free(&a);
        return nullptr;
    }
    jfloatArray out = env->NewFloatArray(a.n_samples);
    if (out) env->SetFloatArrayRegion(out, 0, a.n_samples, a.samples);
    qt_audio_free(&a);
    return out;
}

}  // extern "C"
