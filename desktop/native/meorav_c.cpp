// libmeorav (desktop): a flat C API over qwentts.cpp (qwen.h) for Python ctypes.
//
// Same call sequence as the Android JNI bridge (android/app/src/main/cpp/meorav_jni.cpp): one
// synthesis at a time, progress and cancellation through qt_tts_params.cancel, which qwentts
// polls once per 12.5 Hz codec frame (80 ms of audio). Flat functions with plain types only, so
// the Python side never mirrors qwen.h's structs (whose layout changes with QT_ABI_VERSION).
#include <atomic>
#include <cstdio>
#include <cstring>
#include <string>
#include "qwen.h"

static std::atomic<int>  g_frames{0};
static std::atomic<bool> g_cancel{false};
static std::atomic<bool> g_verbose{false};
static std::string       g_last_error;

static void log_cb(enum qt_log_level level, const char * msg, void *) {
    if (level == QT_LOG_ERROR || level == QT_LOG_WARN || g_verbose.load()) {
        fprintf(stderr, "[qwentts] %s", msg);
        size_t n = strlen(msg);
        if (n == 0 || msg[n - 1] != '\n') fputc('\n', stderr);
    }
}

static bool cancel_cb(void *) {
    g_frames.fetch_add(1, std::memory_order_relaxed);
    return g_cancel.load(std::memory_order_relaxed);
}

static void set_error(const char * prefix) {
    const char * e = qt_last_error();
    g_last_error = std::string(prefix) + (e && *e ? e : "unknown error");
}

extern "C" {

__attribute__((visibility("default"))) const char * meorav_version(void) { return qt_version(); }
__attribute__((visibility("default"))) const char * meorav_last_error(void) { return g_last_error.c_str(); }
__attribute__((visibility("default"))) void meorav_set_verbose(int on) { g_verbose.store(on != 0); }

// Returns a handle, or NULL (see meorav_last_error).
__attribute__((visibility("default"))) void * meorav_init(const char * talker, const char * codec,
                                                          float chunk_sec) {
    qt_log_set(log_cb, nullptr);
    struct qt_init_params p;
    qt_init_default_params(&p);
    p.talker_path     = talker;
    p.codec_path      = codec;
    p.max_batch       = 1;
    p.codec_chunk_sec = chunk_sec;  // device stays NULL: only the CPU backend is compiled in
    struct qt_context * q = qt_init(&p);
    if (!q) set_error("load failed: ");
    return q;
}

__attribute__((visibility("default"))) void meorav_free(void * h) {
    qt_free(static_cast<struct qt_context *>(h));
}

__attribute__((visibility("default"))) int meorav_n_speakers(void * h) {
    return h ? qt_n_speakers(static_cast<struct qt_context *>(h)) : 0;
}

__attribute__((visibility("default"))) const char * meorav_speaker_name(void * h, int i) {
    return h ? qt_speaker_name(static_cast<struct qt_context *>(h), i) : "";
}

__attribute__((visibility("default"))) const char * meorav_model_type(void * h) {
    return h ? qt_model_type(static_cast<struct qt_context *>(h)) : "";
}

__attribute__((visibility("default"))) int  meorav_progress_frames(void) { return g_frames.load(); }
__attribute__((visibility("default"))) void meorav_cancel(void) { g_cancel.store(true); }

// Synthesises mono float PCM. On success returns the sample count (> 0), sets *out to a
// malloc'd buffer (release with meorav_free_audio) and *sample_rate (24000). On failure or
// cancel returns a negative qt_status and sets meorav_last_error.
__attribute__((visibility("default"))) int meorav_synthesize(void * h, const char * text, const char * lang,
                                                             const char * speaker, long long seed,
                                                             float ** out, int * sample_rate) {
    *out         = nullptr;
    *sample_rate = 0;
    auto * q     = static_cast<struct qt_context *>(h);
    if (!q) {
        g_last_error = "model not loaded";
        return QT_STATUS_INVALID_PARAMS;
    }
    struct qt_tts_params p;
    qt_tts_default_params(&p);
    p.text    = text;
    p.lang    = (lang && *lang) ? lang : nullptr;
    p.speaker = (speaker && *speaker) ? speaker : nullptr;
    p.seed    = seed;
    p.cancel  = cancel_cb;
    g_frames.store(0);
    g_cancel.store(false);
    struct qt_audio a = {};
    enum qt_status  rc = qt_synthesize(q, &p, &a);
    if (rc != QT_STATUS_OK) {
        set_error(rc == QT_STATUS_CANCELLED ? "cancelled: " : "synthesis failed: ");
        qt_audio_free(&a);
        return rc < 0 ? rc : -3;
    }
    *out         = a.samples;  // ownership passes to the caller (freed with free())
    *sample_rate = a.sample_rate;
    return a.n_samples;
}

__attribute__((visibility("default"))) void meorav_free_audio(float * samples) { free(samples); }

}  // extern "C"
