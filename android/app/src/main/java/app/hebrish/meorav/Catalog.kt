package app.hebrish.meorav

import android.content.Context
import android.util.Log
import org.json.JSONObject
import java.io.File
import java.net.HttpURLConnection
import java.net.URL

data class ModelFile(val role: String, val name: String, val url: String, val size: Long, val sha256: String)
data class Quant(val id: String, val label: String, val isDefault: Boolean, val minRamGb: Int, val note: String, val files: List<ModelFile>) {
    val totalBytes: Long get() = files.sumOf { it.size }
    fun file(role: String) = files.first { it.role == role }
}
data class Voice(val id: String, val name: String, val version: String, val speaker: String, val lang: String,
                 val description: String, val hfRepo: String, val quants: List<Quant>)

/**
 * The model catalogue: which voice versions exist, their quantisations, file URLs, sizes and
 * SHA-256. Source of truth is catalog/catalog.json in the repo, published at [REMOTE_URL] and
 * bundled into assets at build time. A newer remote copy is cached in filesDir and wins, so a new
 * voice version needs only a CDN upload and a catalogue rewrite, no app release.
 */
object Catalog {
    const val REMOTE_URL = "https://cdn.hebrish.app/models/meorav/catalog.json"
    private const val TAG = "MeoravCatalog"

    @Volatile var voices: List<Voice> = emptyList(); private set

    fun load(ctx: Context) {
        val cached = File(ctx.filesDir, "catalog.json")
        voices = (if (cached.exists()) runCatching { parse(cached.readText()) }.getOrNull() else null)
            ?: parse(ctx.assets.open("catalog.json").bufferedReader().use { it.readText() })
    }

    /** Fetch the remote catalogue; keep it only if it parses and lists at least one voice. Blocking. */
    fun refresh(ctx: Context): Boolean = runCatching {
        val c = URL(REMOTE_URL).openConnection() as HttpURLConnection
        c.connectTimeout = 15000; c.readTimeout = 15000
        c.setRequestProperty("User-Agent", "Meorav-Android/${BuildConfig.VERSION_NAME}")
        c.setRequestProperty("Cache-Control", "no-cache")
        if (c.responseCode != 200) return false
        val text = c.inputStream.bufferedReader().use { it.readText() }
        val v = parse(text)
        if (v.isEmpty()) return false
        File(ctx.filesDir, "catalog.json").writeText(text)
        voices = v
        true
    }.onFailure { Log.w(TAG, "refresh failed: $it") }.getOrDefault(false)

    fun parse(text: String): List<Voice> {
        val o = JSONObject(text)
        require(o.getInt("schema") == 1) { "unknown catalogue schema" }
        val vs = o.getJSONArray("voices")
        return (0 until vs.length()).map { i ->
            val v = vs.getJSONObject(i)
            val qs = v.getJSONArray("quants")
            Voice(
                v.getString("id"), v.getString("name"), v.getString("version"), v.getString("speaker"),
                v.optString("lang", "english"), v.optString("description"), v.optString("hf_repo"),
                (0 until qs.length()).map { j ->
                    val q = qs.getJSONObject(j)
                    val fs = q.getJSONArray("files")
                    Quant(q.getString("id"), q.getString("label"), q.optBoolean("default"), q.optInt("min_ram_gb", 8),
                        q.optString("note"),
                        (0 until fs.length()).map { k ->
                            val f = fs.getJSONObject(k)
                            ModelFile(f.getString("role"), f.getString("name"), f.getString("url"), f.getLong("size"), f.getString("sha256"))
                        })
                })
        }
    }
}
