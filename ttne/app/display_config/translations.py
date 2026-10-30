"""Touchscreen translation file: download, checked upload and reset.

The touchscreen (cmdisplay) reads its texts from a CSV table: one row per
text, one column per language headed "Name (code)", for example
"Français (fr)". The English column is the key. The image installs the
default table with the app; an uploaded table is stored in CUSTOM_FILE,
which the display uses instead and watches: it restarts when it changes.

CUSTOM_FILE holds only what differs from the default table (changed texts
and added languages), so texts not changed by the customer still improve
with firmware updates. Downloads merge both.

Every uploaded text is checked with the same rules the display applies
before using it; the display falls back to the built-in text for anything
rejected.
"""
import csv
import io
import os
import re
import threading

DEFAULT_FILE = "/usr/share/cmdisplay/assets/translations.csv"
CUSTOM_FILE = "/home/root/.cmdisplay.translations.csv"

# Languages built into the display, in the order of its Language list.
BUILTIN = (
    ("en", "English"),
    ("es", "Español"),
    ("de", "Deutsch"),
    ("zh-hans", "中文 (简体)"),
    ("ar", "العربية"),
)
MAX_LANGUAGES = 16          # the display's limit, built-in ones included
MAX_TEXT_BYTES = 1024
MAX_FILE_BYTES = 2 * 1024 * 1024
MAX_CODE_LEN = 15
MAX_NAME_BYTES = 63

CODE = re.compile(r"^[a-z]{2,3}(?:-[a-z0-9]{2,8})?$")
TITLE_CODE = re.compile(r"\(\s*([A-Za-z]{2,3}(?:-[A-Za-z0-9]{2,8})?)\s*\)\s*$")
# Column titles without a code: the customer workbook's and plain names.
TITLE_ALIASES = {
    "english": "en", "english (reference)": "en", "inglés": "en",
    "spanish": "es", "español": "es", "espanol": "es",
    "german": "de", "deutsch": "de", "alemán": "de",
    "chinese": "zh-hans", "chinese (simplified)": "zh-hans", "中文": "zh-hans",
    "中文 (简体)": "zh-hans", "简体中文": "zh-hans",
    "arabic": "ar", "العربية": "ar",
}
ID_TITLES = ("id", "text_id", "text id")
SCREEN_TITLES = ("screen", "pantalla")
NOTES_TITLE = "Must keep unchanged"

# printf conversions the display accepts, as in its i18n.c.
CONVERSION = re.compile(r"%[-+ #0]*[0-9]*(?:\.[0-9]*)?(?:hh|ll|h|l|z)?[diouxXeEfFgGcs%]")

# Characters the touchscreen can show. Its fonts are Montserrat (Latin,
# Cyrillic), DejaVu Sans (Greek, Arabic, Hebrew, symbols) and WenQuanYi Zen
# Hei (Chinese, Japanese, Korean). Arabic letters are limited to the ones
# LVGL can join (Arabic and Persian): Urdu's own letters aren't. Scripts that
# need complex shaping (Thai, Indic...) are not listed.
SUPPORTED = (
    (0x0020, 0x007E), (0x00A0, 0x024F), (0x02B0, 0x02FF),   # Latin
    (0x0370, 0x03FF),                                       # Greek
    (0x0400, 0x052F),                                       # Cyrillic
    (0x05BE, 0x05BE), (0x05D0, 0x05EA), (0x05F0, 0x05F4),   # Hebrew
    (0x060C, 0x060C), (0x061B, 0x061B), (0x061F, 0x061F),   # Arabic punctuation
    (0x0621, 0x0652), (0x0660, 0x066D), (0x0670, 0x0670),   # Arabic
    (0x067E, 0x067E), (0x0686, 0x0686), (0x0698, 0x0698),   # Persian
    (0x06A9, 0x06A9), (0x06AF, 0x06AF), (0x06CC, 0x06CC),
    (0x06F0, 0x06F9),
    (0x1E00, 0x1EFF),                                       # Latin (Vietnamese)
    (0x200E, 0x200F), (0x2010, 0x2027), (0x2030, 0x205E),   # punctuation
    (0x20A0, 0x20BF), (0x2100, 0x214F), (0x2190, 0x21FF),   # currency, symbols
    (0x2200, 0x22FF), (0x2460, 0x27BF),                     # symbols, dingbats
    (0x3000, 0x303F), (0x3040, 0x30FF), (0x3100, 0x312F),   # CJK, kana
    (0x3130, 0x318F), (0x31F0, 0x31FF),
    (0x3400, 0x4DBF), (0x4E00, 0x9FFF), (0xAC00, 0xD7A3),   # ideographs, Hangul
    (0xF900, 0xFAFF), (0xFE30, 0xFE4F), (0xFF00, 0xFFEF),
    (0xFB50, 0xFDFF), (0xFE70, 0xFEFC),                     # Arabic forms
)

_lock = threading.Lock()


class TranslationFileError(ValueError):
    """The upload can't be used at all. code names the problem for the UI."""

    def __init__(self, code, detail=""):
        super().__init__(f"{code}: {detail}" if detail else code)
        self.code = code
        self.detail = detail


# ---- Checks -----------------------------------------------------------------

def _supported(char):
    value = ord(char)
    if char == "\n":
        return True
    return any(low <= value <= high for low, high in SUPPORTED)


def _conversions(text):
    """The text's printf conversions, None if a '%' starts none."""
    found = CONVERSION.findall(text)
    if text.count("%") != sum(c.count("%") for c in found):
        return None
    return found


def text_problem(english, text):
    """Why a translation of english can't be used: (code, detail), or None."""
    if len(text.encode("utf-8")) > MAX_TEXT_BYTES:
        return ("too_long", str(MAX_TEXT_BYTES))
    controls = [c for c in text if c != "\n" and (ord(c) < 0x20 or 0x7F <= ord(c) < 0xA0)]
    if controls:
        return ("control_chars", "")
    conversions = _conversions(text)
    if conversions is None or conversions != _conversions(english):
        return ("placeholders", " ".join(_conversions(english) or []))
    if text.count("#") != english.count("#"):
        return ("colour_marks", str(english.count("#")))
    unsupported = "".join(dict.fromkeys(c for c in text if not _supported(c)))
    if unsupported:
        return ("unsupported_chars", unsupported[:10])
    return None


def must_keep(english):
    """What every translation of english has to keep, for the download."""
    notes = []
    conversions = [c for c in _conversions(english) or [] if c != "%%"]
    if conversions:
        notes.append("Placeholders: " + "  ".join(dict.fromkeys(conversions)))
    if english.count("#"):
        notes.append("Colour marks: keep each \"#A1C61A \" and \"#\" around the same words")
    if "\n" in english:
        notes.append("Line breaks: keep them (Alt+Enter in Excel)")
    return "\n".join(notes)


# ---- Reading tables ---------------------------------------------------------

def _decode(data):
    if len(data) > MAX_FILE_BYTES:
        raise TranslationFileError("too_large", str(MAX_FILE_BYTES))
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError as ex:
        raise TranslationFileError("not_utf8") from ex
    # Line breaks inside cells: Excel writes "\r\n"
    return text.replace("\r\n", "\n").replace("\r", "\n")


def _separator(text):
    """The display's rule: the commonest of , ; and tab in the header line."""
    header = []
    quoted = False
    for char in text:
        if char == '"':
            quoted = not quoted
        elif char == "\n" and not quoted:
            break
        elif not quoted:
            header.append(char)
    counts = {sep: header.count(sep) for sep in (",", ";", "\t")}
    if counts[";"] > counts[","] and counts[";"] >= counts["\t"]:
        return ";"
    return "\t" if counts["\t"] > counts[","] else ","


def _column_title(title):
    """(code, name) of a language column title, None for other columns."""
    title = title.strip()
    match = TITLE_CODE.search(title)
    if match:
        code = match.group(1).lower()
        name = title[:match.start()].strip()
        return (code, name) if CODE.match(code) and len(code) <= MAX_CODE_LEN else None
    alias = TITLE_ALIASES.get(title.lower())
    if alias:
        return (alias, dict(BUILTIN)[alias])
    return None


def parse_table(data):
    """Parses CSV bytes into a table:
    {"languages": [(code, name)...], "columns": {code: index}, "id": index,
     "screen": index, "rows": [(row_number, cells)...], "ignored": [titles]}.
    """
    text = _decode(data)
    rows = list(csv.reader(io.StringIO(text, newline=""), delimiter=_separator(text)))
    if not rows:
        raise TranslationFileError("empty")
    table = {"languages": [], "columns": {}, "id": None, "screen": None, "rows": [],
             "ignored": []}
    for index, title in enumerate(rows[0]):
        lowered = title.strip().lower()
        if lowered in ID_TITLES and table["id"] is None:
            table["id"] = index
            continue
        if lowered in SCREEN_TITLES and table["screen"] is None:
            table["screen"] = index
            continue
        language = _column_title(title)
        if language is None or language[0] in table["columns"]:
            if title.strip() and title.strip() != NOTES_TITLE:
                table["ignored"].append(title.strip())
            continue
        table["columns"][language[0]] = index
        table["languages"].append(language)
    if "en" not in table["columns"]:
        raise TranslationFileError("no_english")
    for number, cells in enumerate(rows[1:], start=2):
        if any(cell.strip() for cell in cells):
            table["rows"].append((number, cells))
    return table


def _cell(cells, index):
    return cells[index] if index is not None and index < len(cells) else ""


def _read(path):
    try:
        with open(path, "rb") as f:
            return parse_table(f.read())
    except (OSError, TranslationFileError):
        return None


def _texts(table):
    """{english: {code: text}} of a table's non-empty cells."""
    texts = {}
    for _, cells in table["rows"]:
        english = _cell(cells, table["columns"]["en"])
        if english and english not in texts:
            texts[english] = {code: _cell(cells, index)
                              for code, index in table["columns"].items()
                              if _cell(cells, index)}
    return texts


def default_table(path=None):
    path = path or DEFAULT_FILE
    table = _read(path)
    if table is None:
        raise TranslationFileError("no_default", path)
    return table


# ---- Public functions -------------------------------------------------------

def languages(custom_path=None):
    """[(code, name)] the display offers: built-in, then the custom file's."""
    custom_path = custom_path or CUSTOM_FILE
    result = list(BUILTIN)
    custom = _read(custom_path)
    for code, name in (custom["languages"] if custom else []):
        if code not in dict(result) and len(result) < MAX_LANGUAGES:
            result.append((code, name or code))
    return result


def language_codes(custom_path=None):
    custom_path = custom_path or CUSTOM_FILE
    return [code for code, _ in languages(custom_path)]


def info(custom_path=None):
    custom_path = custom_path or CUSTOM_FILE
    try:
        modified = int(os.stat(custom_path).st_mtime)
    except OSError:
        modified = None
    return {
        "custom": modified is not None,
        "modified": modified,
        "languages": [{"code": code, "name": name} for code, name in languages(custom_path)],
    }


def export_csv(default_path=None, custom_path=None):
    """The table in use: default texts with the custom file's changes, in
    the default file's order, as UTF-8 CSV with a byte order mark (Excel)."""
    custom_path = custom_path or CUSTOM_FILE
    default = default_table(default_path)
    custom = _read(custom_path)
    langs = list(default["languages"])
    for code, name in (custom["languages"] if custom else []):
        if code not in dict(langs) and len(langs) < MAX_LANGUAGES:
            langs.append((code, name or code))
    changes = _texts(custom) if custom else {}

    out = io.StringIO()
    writer = csv.writer(out, lineterminator="\r\n")
    writer.writerow(["ID", "Screen"] + [f"{name} ({code})" for code, name in langs] + [NOTES_TITLE])
    for _, cells in default["rows"]:
        english = _cell(cells, default["columns"]["en"])
        changed = changes.get(english, {})
        texts = [english]
        for code, _ in langs[1:]:
            texts.append(changed.get(code) or _cell(cells, default["columns"].get(code)))
        writer.writerow([_cell(cells, default["id"]), _cell(cells, default["screen"])] + texts +
                        [must_keep(english)])
    return "﻿" + out.getvalue()


def import_csv(data, default_path=None):
    """Checks an uploaded table. Returns (csv_text, report): csv_text holds
    the accepted texts that differ from the default table (None if nothing
    does), report what was accepted and rejected. Raises
    TranslationFileError if the table can't be used."""
    default = default_table(default_path)
    upload = parse_table(data)

    default_rows = []          # (id, screen, english, {code: text})
    by_english = {}
    by_stripped = {}
    for _, cells in default["rows"]:
        english = _cell(cells, default["columns"]["en"])
        texts = {code: _cell(cells, index) for code, index in default["columns"].items()}
        default_rows.append((_cell(cells, default["id"]), _cell(cells, default["screen"]),
                             english, texts))
        by_english.setdefault(english, len(default_rows) - 1)
        by_stripped.setdefault(english.strip(), len(default_rows) - 1)

    langs = [lang for lang in default["languages"] if lang[0] != "en"]
    for code, name in upload["languages"]:
        if code in dict(default["languages"]):
            continue
        if len(langs) + 1 >= MAX_LANGUAGES:
            raise TranslationFileError("too_many_languages", str(MAX_LANGUAGES))
        if not name or len(name.encode("utf-8")) > MAX_NAME_BYTES or \
                not all(_supported(c) and c != "\n" for c in name):
            name = code
        langs.append((code, name))
    new_codes = [code for code, _ in langs if code not in dict(default["languages"])]
    uploaded_codes = [code for code, _ in langs if code in upload["columns"]]

    report = {"languages": uploaded_codes, "new_languages": new_codes, "checked": 0,
              "accepted": 0, "changed": 0, "rejected": [], "ignored_columns": upload["ignored"]}
    changes = {}               # default row index -> {code: text}
    for number, cells in upload["rows"]:
        english = _cell(cells, upload["columns"]["en"]).replace("\r", "")
        row_id = _cell(cells, upload["id"]).strip()
        index = by_english.get(english, by_stripped.get(english.strip()))
        if index is None:
            if any(_cell(cells, upload["columns"][c]) for c in uploaded_codes):
                report["rejected"].append({"row": number, "id": row_id, "language": "en",
                                           "reason": "unknown_text", "detail": english[:80]})
            continue
        row_id, _, english, defaults = default_rows[index]
        for code in uploaded_codes:
            text = _cell(cells, upload["columns"][code])
            if not text:
                continue
            report["checked"] += 1
            problem = text_problem(english, text)
            if problem:
                report["rejected"].append({"row": number, "id": row_id, "language": code,
                                           "reason": problem[0], "detail": problem[1]})
                continue
            report["accepted"] += 1
            if text != defaults.get(code, ""):
                changes.setdefault(index, {})[code] = text
    report["changed"] = sum(len(texts) for texts in changes.values())

    # Columns: the built-in languages with changes, then every new language
    # (kept even without texts so it stays in the Language list).
    stored = [lang for lang in langs
              if lang[0] in new_codes or any(lang[0] in t for t in changes.values())]
    if not stored:
        return None, report
    out = io.StringIO()
    writer = csv.writer(out, lineterminator="\n")
    writer.writerow(["ID", "Screen", "English (en)"] + [f"{name} ({code})" for code, name in stored])
    for index in sorted(changes):
        row_id, screen, english, _ = default_rows[index]
        writer.writerow([row_id, screen, english] + [changes[index].get(code, "") for code, _ in stored])
    return out.getvalue(), report


def save_custom(text, path=None):
    """Replaces the custom file in one step: the display never reads half a
    file. None (no changes) removes it."""
    path = path or CUSTOM_FILE
    with _lock:
        if text is None:
            _remove(path)
            return
        temporary = path + ".tmp"
        try:
            with open(temporary, "w", encoding="utf-8", newline="") as f:
                f.write(text)
                f.flush()
                os.fsync(f.fileno())
            os.replace(temporary, path)
        except OSError:
            try:
                os.unlink(temporary)
            except OSError:
                pass
            raise


def _remove(path):
    try:
        os.unlink(path)
    except FileNotFoundError:
        pass


def reset(path=None):
    path = path or CUSTOM_FILE
    with _lock:
        _remove(path)
