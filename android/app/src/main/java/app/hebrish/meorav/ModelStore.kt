package app.hebrish.meorav

import android.content.Context
import java.io.File
import java.io.FileInputStream
import java.io.FileOutputStream
import java.io.IOException
import java.net.HttpURLConnection
import java.net.URL
import java.security.MessageDigest

/**
 * Model files in app-specific storage: filesDir/models/<voice id>/<file name>.
 *
 * A file is downloaded to `<name>.part`, hashed while it streams, and renamed to `<name>` only
 * after its size and SHA-256 match the catalogue. So "the final file exists with the right size"
 * means "verified". An interrupted download resumes from the `.part` with an HTTP Range request
 * (the bytes already on disk are re-hashed first).
 */
object ModelStore {
    fun dir(ctx: Context, voice: Voice) = File(ctx.filesDir, "models/${voice.id}").apply { mkdirs() }
    fun path(ctx: Context, voice: Voice, f: ModelFile) = File(dir(ctx, voice), f.name)

    fun isReady(ctx: Context, voice: Voice, q: Quant) = q.files.all { path(ctx, voice, it).let { p -> p.exists() && p.length() == it.size } }

    /** Bytes still to download for [q] (partial downloads count as done). */
    fun remaining(ctx: Context, voice: Voice, q: Quant) = q.files.sumOf { f ->
        val p = path(ctx, voice, f)
        if (p.exists() && p.length() == f.size) 0L else f.size - File(p.path + ".part").length().coerceAtMost(f.size)
    }

    /** Bytes on disk for this voice (all quants, partials included). */
    fun usedBytes(ctx: Context, voice: Voice) = dir(ctx, voice).listFiles()?.sumOf { it.length() } ?: 0L

    fun delete(ctx: Context, voice: Voice, q: Quant) {
        q.files.forEach { f -> path(ctx, voice, f).delete(); File(path(ctx, voice, f).path + ".part").delete() }
    }

    class Cancelled : IOException("cancelled")

    /** Download every missing file of [q]. [progress] gets (bytes done, bytes total) for the quant. Blocking. */
    fun download(ctx: Context, voice: Voice, q: Quant, cancelled: () -> Boolean, progress: (Long, Long) -> Unit) {
        val total = q.totalBytes
        val need = remaining(ctx, voice, q)
        val free = dir(ctx, voice).usableSpace
        if (free < need + 200L * 1024 * 1024) {
            throw IOException("Not enough free space: need ${Format.bytes(need)} plus some room, have ${Format.bytes(free)}")
        }
        var doneBefore = 0L
        for (f in q.files) {
            val dest = path(ctx, voice, f)
            if (dest.exists() && dest.length() == f.size) { doneBefore += f.size; continue }
            fetch(f, File(dest.path + ".part"), dest, cancelled) { n -> progress(doneBefore + n, total) }
            doneBefore += f.size
        }
        progress(total, total)
    }

    private fun fetch(f: ModelFile, part: File, dest: File, cancelled: () -> Boolean, progress: (Long) -> Unit) {
        val md = MessageDigest.getInstance("SHA-256")
        val buf = ByteArray(1 shl 20)
        var have = part.length()
        if (have > f.size) { part.delete(); have = 0 }
        if (have > 0) FileInputStream(part).use { inp ->
            while (true) { val n = inp.read(buf); if (n < 0) break; md.update(buf, 0, n); if (cancelled()) throw Cancelled() }
        }
        if (have < f.size) {
            val c = URL(f.url).openConnection() as HttpURLConnection
            c.connectTimeout = 20000; c.readTimeout = 60000
            c.setRequestProperty("User-Agent", "Meorav-Android/${BuildConfig.VERSION_NAME}")
            if (have > 0) c.setRequestProperty("Range", "bytes=$have-")
            val code = c.responseCode
            val append = when (code) {
                206 -> true
                200 -> { md.reset(); have = 0; false }      // server ignored the Range: start over
                416 -> { md.reset(); part.delete(); throw IOException("Server refused the resume (416); retry to start ${f.name} again") }
                else -> throw IOException("HTTP $code for ${f.url}")
            }
            c.inputStream.use { inp ->
                FileOutputStream(part, append).use { out ->
                    var lastReport = 0L
                    while (true) {
                        if (cancelled()) throw Cancelled()
                        val n = inp.read(buf)
                        if (n < 0) break
                        out.write(buf, 0, n); md.update(buf, 0, n); have += n
                        if (have - lastReport > (4 shl 20)) { progress(have); lastReport = have }
                    }
                }
            }
        }
        if (part.length() != f.size) throw IOException("${f.name}: got ${part.length()} bytes, expected ${f.size}. Retry to resume.")
        val hex = md.digest().joinToString("") { "%02x".format(it) }
        if (hex != f.sha256) { part.delete(); throw IOException("${f.name}: checksum mismatch, deleted. Retry to download again.") }
        if (!part.renameTo(dest)) throw IOException("could not move ${part.name} into place")
        progress(f.size)
    }
}
