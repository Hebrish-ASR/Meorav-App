package app.hebrish.meorav

import java.util.Locale

object Format {
    fun bytes(b: Long): String = when {
        b >= 1_000_000_000L -> String.format(Locale.US, "%.2f GB", b / 1e9)
        b >= 1_000_000L -> String.format(Locale.US, "%.0f MB", b / 1e6)
        else -> String.format(Locale.US, "%d KB", b / 1000)
    }
    fun secs(s: Double): String = String.format(Locale.US, "%.1f s", s)
}
