"""Russian text normalization for TTS preprocessing.

Handles:
- Numbers → words (num2words)
- Quotes and dashes normalization
- Abbreviation expansion
- Special character cleanup
"""

import re

# ── Quote normalization ──────────────────────────────────────

# Pattern for ASCII quotes and apostrophes that act as quotes
# We only replace " that are at word boundaries (preceded/followed by space/punctuation)
# or at start/end of text. Apostrophes inside words (Д'Артаньян) are left alone.
_QUOTE_PATTERNS = [
    # Double quotes: "word" or " word " - balanced pairs
    (re.compile(r'(^|[\s(\[{\'\"«])"([^"]+?)"(?=[\s)\]}?!,.:;\'\"»]|$)'), r'\1«\2»'),
    # Single quotes used as quotes: 'word' - but NOT inside words
    (re.compile(r"(^|[\s(\[{\"\«])'([^']+?)'(?=[\s)\]}?!,.:;'\«]|$)"), r"\1«\2»"),
]

# For unpaired quotes, we still need position-based fallback
def normalize_quotes(text: str) -> str:
    """Normalize ASCII quotes to «ёлочки», preserving apostrophes inside words.

    Strategy:
    1. First, replace balanced pairs using regex patterns
    2. Then handle any remaining unpaired quotes with position-based logic
       that ignores apostrophes between letters
    """
    if not text:
        return text

    # Step 1: Replace balanced quote pairs
    for pattern, repl in _QUOTE_PATTERNS:
        text = pattern.sub(repl, text)

    # Step 2: Handle remaining unpaired quotes
    # We iterate char by char but treat apostrophe between letters as literal
    result = []
    open_quote = True

    for i, ch in enumerate(text):
        if ch == '"':
            # Check if it's an apostrophe-like usage (between letters)
            prev_char = text[i - 1] if i > 0 else ''
            next_char = text[i + 1] if i + 1 < len(text) else ''

            # If it's between two Cyrillic/Latin letters, treat as apostrophe
            if _is_letter(prev_char) and _is_letter(next_char):
                result.append(''')
            else:
                result.append('«' if open_quote else '»')
                open_quote = not open_quote

        elif ch in ("'", "`", "´"):
            # Check if it's an apostrophe inside a word (between letters)
            prev_char = text[i - 1] if i > 0 else ''
            next_char = text[i + 1] if i + 1 < len(text) else ''

            if _is_letter(prev_char) and _is_letter(next_char):
                result.append(''')  # Keep as apostrophe
            else:
                result.append('«' if open_quote else '»')
                open_quote = not open_quote
        else:
            result.append(ch)

    return "".join(result)


def _is_letter(ch: str) -> bool:
    """Check if character is a letter (Cyrillic or Latin)."""
    return bool(re.match(r'[а-яёА-ЯЁa-zA-Z]', ch))


# ── Dash normalization ───────────────────────────────────────


def normalize_dashes(text: str) -> str:
    """Normalize various dash types to em-dash (—)."""
    # Hyphen-minus and en-dash surrounded by spaces → em-dash
    text = re.sub(r' ([-\u2013]) ', ' — ', text)
    # Double hyphen → em-dash
    text = text.replace('--', '\u2014')
    # Unicode em-dash already OK
    return text


# ── Abbreviation expansion ───────────────────────────────────

# Note: expansion values do NOT include leading conjunctions/words
# that are already present in context (e.g., "и тому подобное" → "тому подобное")
_ABBREVIATIONS = {
    "т. е.": "то есть",
    "т.е.": "то есть",
    "т. к.": "так как",
    "т.н.": "так называемый",
    "т. д.": "далее",
    "т.д.": "далее",
    "т. п.": "прочее",
    "т.п.": "прочее",
    "др.": "другие",
    "пр.": "прочее",
    "см.": "смотри",
    "напр.": "например",
    "ок.": "около",
    "прим.": "примечание",
    "рис.": "рисунок",
    "табл.": "таблица",
    "гл.": "глава",
    "стр.": "страница",
    "тел.": "телефон",
    "руб.": "рублей",
    "долл.": "долларов",
    "тыс.": "тысяч",
    "млн.": "миллионов",
    "млрд.": "миллиардов",
    "г.": "год",
    "гг.": "годы",
    "в.": "век",
    "вв.": "века",
    "до н.э.": "до нашей эры",
    "н.э.": "нашей эры",
    # English
    "e.g.": "например",
    "i.e.": "то есть",
    "etc.": "и так далее",
    "vs.": "против",
}

# Compile regex patterns with word boundaries and case insensitivity
_ABBR_PATTERNS = []
for abbr, expansion in _ABBREVIATIONS.items():
    # Escape for regex, then add word boundary constraints
    # For abbreviations ending with dot, require space/punctuation/end after
    escaped = re.escape(abbr)
    # Pattern: not preceded by letter, followed by space/punct/end
    pattern = re.compile(
        rf'(?<![а-яёА-ЯЁa-zA-Z]){escaped}(?=[\s\]]?[.,!?;:]?(?:\s|$))',
        re.IGNORECASE
    )
    _ABBR_PATTERNS.append((pattern, expansion))


def expand_abbreviations(text: str) -> str:
    """Expand common Russian abbreviations with word boundaries and case preservation."""
    if not text:
        return text

    def _replace(match):
        matched = match.group(0)
        # Preserve case: if first char was uppercase, capitalize expansion
        if matched and matched[0].isupper():
            return expansion.capitalize()
        return expansion

    # Sort by length descending to match longest first
    sorted_patterns = sorted(_ABBR_PATTERNS, key=lambda x: -len(x[0].pattern))
    for pattern, expansion in sorted_patterns:
        text = pattern.sub(_replace, text)

    return text


# ── Number to words ──────────────────────────────────────────

# Pattern for numbers with optional ordinal suffixes, percentages, currency
_NUM_RE = re.compile(r'-?\d+(?:[.,]\d+)?')
# Pattern for ordinals with suffixes (5-й, 21-я, 5-е, 3-м, 90-х, 21-го, 5-му)
_ORDINAL_RE = re.compile(r'-?\d+(?:[.,]\d+)?[-–](?:[йяеиаоуыь]|[мх]|[гр][оу]?)\b')
_PERCENT_RE = re.compile(r'-?\d+(?:[.,]\d+)?\s*%')
_CURRENCY_RE = re.compile(r'[₽$€£¥]\s*-?\d+(?:[.,]\d+)?|-?\d+(?:[.,]\d+)?\s*[₽$€£¥]')
# Year pattern: 4-digit year with optional "г." / "гг." (dot is mandatory)
_YEAR_RE = re.compile(r'\b(1\d{3}|20\d{2})\s*(?:г\.|гг\.)?\b(?!\w)')


def _convert_number(num_str: str, ordinal: bool = False, gender: str = "masculine", case: str = "nominative") -> str:
    """Convert number string to Russian words.

    Args:
        num_str: Number string to convert.
        ordinal: If True, output ordinal form.
        gender: Grammatical gender (masculine/feminine/neuter).
        case: Grammatical case (nominative/genitive/dative/accusative/
              instrumental/prepositional).
    """
    try:
        from num2words import num2words as _n2w
    except ImportError:
        return num_str

    normalized = num_str.replace(",", ".")
    try:
        num = float(normalized)
    except ValueError:
        return num_str

    is_int = "." not in normalized or normalized.endswith(".0")
    try:
        if is_int:
            if ordinal:
                return _n2w(int(num), lang="ru", ordinal=True, gender=gender, case=case)
            return _n2w(int(num), lang="ru")
        else:
            return _n2w(num, lang="ru")
    except (NotImplementedError, OverflowError):
        return num_str


def _replace_percent(m: re.Match) -> str:
    """Replace '50%' → 'пятьдесят процентов'."""
    num_str = m.group(0).replace("%", "").strip()
    words = _convert_number(num_str)
    return f"{words} процентов"


def _replace_currency(m: re.Match) -> str:
    """Replace currency symbols with words."""
    text = m.group(0)
    # Simple mapping
    if "₽" in text or "руб" in text.lower():
        num_str = re.sub(r'[₽рубРУБ]', '', text).strip()
        words = _convert_number(num_str)
        return f"{words} рублей"
    elif "$" in text:
        num_str = text.replace("$", "").strip()
        words = _convert_number(num_str)
        return f"{words} долларов"
    elif "€" in text:
        num_str = text.replace("€", "").strip()
        words = _convert_number(num_str)
        return f"{words} евро"
    elif "£" in text:
        num_str = text.replace("£", "").strip()
        words = _convert_number(num_str)
        return f"{words} фунтов"
    elif "¥" in text:
        num_str = text.replace("¥", "").strip()
        words = _convert_number(num_str)
        return f"{words} йен"
    return text


def _replace_ordinal(m: re.Match) -> str:
    """Replace '5-й' → 'пятый', '21-я' → 'двадцать первая', '3-м' → 'третьим'."""
    full = m.group(0)
    # Extract suffix after hyphen: "5-й" → "й", "21-го" → "го"
    suffix = full.split('-')[-1] if '-' in full else full.split('–')[-1]
    # Number part before hyphen
    num_str = full[:-(len(suffix) + 1)]

    # Map suffix to (gender, case) for num2words
    # Common Russian ordinal suffixes
    _SUFFIX_MAP = {
        'й': ('masculine', 'nominative'),
        'я': ('feminine', 'nominative'),
        'е': ('neuter', 'nominative'),
        'м': ('masculine', 'prepositional'),   # 3-м → третьим
        'х': ('plural', 'prepositional'),       # 90-х → девяностых
        'го': ('masculine', 'genitive'),        # 21-го → двадцать первого
        'му': ('masculine', 'dative'),          # 5-му → пятому
        # Fallback for uncommon suffixes
        'и': ('plural', 'nominative'),
        'ы': ('plural', 'nominative'),
        'о': ('neuter', 'nominative'),
        'у': ('masculine', 'dative'),
        'ю': ('feminine', 'accusative'),
        'а': ('masculine', 'genitive'),
        'ь': ('feminine', 'nominative'),
    }
    gender, case = _SUFFIX_MAP.get(suffix, ('masculine', 'nominative'))
    return _convert_number(num_str, ordinal=True, gender=gender, case=case)


def _replace_year(m: re.Match) -> str:
    """Replace year with proper form: 'в 1990 году' → 'в тысяча девятьсот девяностом году'."""
    year_str = re.sub(r'\s*г\.?', '', m.group(0))
    # For years, we typically use cardinal form with "года/годи"
    # But in prepositional case (в 1990 году) it's special
    # Here we just convert to words; morphological agreement is hard without context
    return _convert_number(year_str)


def normalize_numbers(text: str) -> str:
    """Convert numeric digits to Russian words, handling %, currency, ordinals, years."""
    if not text:
        return text

    # 1. Percentages (before general numbers)
    text = _PERCENT_RE.sub(_replace_percent, text)

    # 2. Currency
    text = _CURRENCY_RE.sub(_replace_currency, text)

    # 3. Ordinals with hyphen (5-й, 24-е, etc.)
    text = _ORDINAL_RE.sub(_replace_ordinal, text)

    # 4. Years with "г." / "гг."
    text = _YEAR_RE.sub(_replace_year, text)

    # 5. General numbers
    def _replace_num(m: re.Match) -> str:
        return _convert_number(m.group(0))

    text = _NUM_RE.sub(_replace_num, text)

    return text


# ── Yo letter ────────────────────────────────────────────────


def normalize_yo(text: str) -> str:
    """Ensure ё is preserved (no-op by default)."""
    return text


# ── Cleanup ──────────────────────────────────────────────────


def cleanup_whitespace(text: str) -> str:
    """Remove excessive whitespace and normalize line breaks."""
    # Replace multiple spaces with one
    text = re.sub(r' {2,}', ' ', text)
    # Replace multiple newlines with one
    text = re.sub(r'\n{3,}', '\n\n', text)
    # Remove spaces before punctuation
    text = re.sub(r'\s+([.,!?;:])', r'\1', text)
    # Ensure space after punctuation (letter following punctuation)
    text = re.sub(r'([.,!?;:])([^\s\d])', r'\1 \2', text)
    return text.strip()


# ── Main cleaning pipeline ───────────────────────────────────


def clean_text(text: str, expand_abbr: bool = True, convert_numbers: bool = True) -> str:
    """Apply full Russian text normalization pipeline.

    Order matters for consistency:
    1. Baseline whitespace cleanup
    2. Quotes normalization («»)
    3. Dashes normalization (—)
    4. Abbreviation expansion (т.д. → далее)
    5. Numbers → words (42 → сорок два)
    6. Final whitespace cleanup
    """
    if not text or not text.strip():
        return ""

    text = cleanup_whitespace(text)
    text = normalize_quotes(text)
    text = normalize_dashes(text)
    if expand_abbr:
        text = expand_abbreviations(text)
    if convert_numbers:
        text = normalize_numbers(text)
    text = normalize_yo(text)
    text = cleanup_whitespace(text)
    return text