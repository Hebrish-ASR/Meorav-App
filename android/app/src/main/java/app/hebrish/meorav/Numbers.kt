package app.hebrish.meorav

/**
 * Spell out digits before synthesis: Meorav was trained on text with numbers written as words,
 * and reads digits poorly. Simple English rules: integers (commas allowed), decimals, years
 * 1100-2099 read as pairs ("nineteen eighty-four", "twenty twenty-six"), "%" as "percent".
 */
object Numbers {
    private val ones = arrayOf("zero", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine", "ten",
        "eleven", "twelve", "thirteen", "fourteen", "fifteen", "sixteen", "seventeen", "eighteen", "nineteen")
    private val tens = arrayOf("", "", "twenty", "thirty", "forty", "fifty", "sixty", "seventy", "eighty", "ninety")
    private val scales = arrayOf("" to 1L, "thousand" to 1_000L, "million" to 1_000_000L, "billion" to 1_000_000_000L, "trillion" to 1_000_000_000_000L)
    private val pattern = Regex("""(?<![\w.])(\d{1,3}(?:,\d{3})+|\d+)(?:\.(\d+))?(%?)""")

    fun spell(text: String): String = pattern.replace(text) { m ->
        val intPart = m.groupValues[1]
        val frac = m.groupValues[2]
        val pct = m.groupValues[3]
        val digits = intPart.replace(",", "")
        val words = when {
            digits.length > 15 -> digits.map { ones[it - '0'] }.joinToString(" ")
            digits.length > 1 && digits.startsWith("0") -> digits.map { ones[it - '0'] }.joinToString(" ")
            frac.isEmpty() && pct.isEmpty() && !intPart.contains(',') && digits.length == 4 && digits.toInt() in 1100..2099 -> year(digits.toInt())
            else -> integer(digits.toLong())
        }
        buildString {
            append(words)
            if (frac.isNotEmpty()) append(" point ").append(frac.map { ones[it - '0'] }.joinToString(" "))
            if (pct.isNotEmpty()) append(" percent")
        }
    }

    fun year(y: Int): String {
        val hi = y / 100; val lo = y % 100
        return when {
            y in 2000..2009 -> integer(y.toLong())
            lo == 0 -> "${under100(hi)} hundred"
            lo < 10 -> "${under100(hi)} oh ${ones[lo]}"
            else -> "${under100(hi)} ${under100(lo)}"
        }
    }

    fun integer(n: Long): String {
        if (n == 0L) return "zero"
        val parts = mutableListOf<String>()
        var rest = n
        for (i in scales.indices.reversed()) {
            val (name, unit) = scales[i]
            val chunk = (rest / unit).toInt()
            if (chunk > 0) { parts += under1000(chunk) + if (name.isEmpty()) "" else " $name"; rest %= unit }
        }
        return parts.joinToString(" ")
    }

    private fun under1000(n: Int): String {
        val h = n / 100; val r = n % 100
        return listOfNotNull(if (h > 0) "${ones[h]} hundred" else null, if (r > 0) (if (h > 0) "and " else "") + under100(r) else null).joinToString(" ")
    }

    private fun under100(n: Int): String = if (n < 20) ones[n] else tens[n / 10] + if (n % 10 > 0) "-${ones[n % 10]}" else ""
}
