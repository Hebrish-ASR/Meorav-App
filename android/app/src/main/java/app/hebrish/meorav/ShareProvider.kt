package app.hebrish.meorav

import android.content.ContentProvider
import android.content.ContentValues
import android.database.Cursor
import android.database.MatrixCursor
import android.net.Uri
import android.os.ParcelFileDescriptor
import android.provider.OpenableColumns
import java.io.File
import java.io.FileNotFoundException

/**
 * Serves WAVs from cacheDir/share/ to the app picked in the share sheet (read-only, by URI
 * grant). A minimal stand-in for androidx FileProvider, since the app uses no AndroidX.
 */
class ShareProvider : ContentProvider() {
    companion object {
        const val AUTHORITY = "app.hebrish.meorav.share"
        fun dir(ctx: android.content.Context) = File(ctx.cacheDir, "share").apply { mkdirs() }
        fun uri(f: File): Uri = Uri.parse("content://$AUTHORITY/${f.name}")
    }

    private fun file(uri: Uri): File {
        val name = uri.lastPathSegment ?: throw FileNotFoundException()
        if (name.contains('/') || name.startsWith(".")) throw FileNotFoundException()
        return File(dir(context!!), name).takeIf { it.exists() } ?: throw FileNotFoundException(name)
    }

    override fun onCreate() = true
    override fun getType(uri: Uri) = "audio/wav"
    override fun openFile(uri: Uri, mode: String): ParcelFileDescriptor =
        ParcelFileDescriptor.open(file(uri), ParcelFileDescriptor.MODE_READ_ONLY)

    override fun query(uri: Uri, projection: Array<out String>?, selection: String?, selectionArgs: Array<out String>?, sortOrder: String?): Cursor {
        val f = file(uri)
        val cols = projection ?: arrayOf(OpenableColumns.DISPLAY_NAME, OpenableColumns.SIZE)
        return MatrixCursor(cols, 1).apply {
            addRow(cols.map { if (it == OpenableColumns.SIZE) f.length() else if (it == OpenableColumns.DISPLAY_NAME) f.name else null })
        }
    }

    override fun insert(uri: Uri, values: ContentValues?): Uri? = null
    override fun delete(uri: Uri, selection: String?, selectionArgs: Array<out String>?) = 0
    override fun update(uri: Uri, values: ContentValues?, selection: String?, selectionArgs: Array<out String>?) = 0
}
