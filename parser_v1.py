"""
parser_v1.py

Lyrics cleaning and timestamp parsing for the car lyrics display.

This module:
- Cleans newly fetched LRCLIB lyrics before they are cached.
- Parses scrubbed synced lyrics into timestamp and lyric lists.
- Preserves timed blank lines so instrumental gaps clear the display.
- Replaces unsupported character runs with one square.
- Marks songs that contain too much unsupported text.

It does not:
- Read or write the cache.
- Contact Spotify or LRCLIB.
- Wrap text for a particular display.
"""

import re
import unicodedata


SCRUB_VERSION = 2

PARTIALLY_SUPPORTED_THRESHOLD = 0.10
UNSUPPORTED_LANGUAGE_THRESHOLD = 0.25

UNSUPPORTED_CHARACTER = "□"


# [01:23.45]
LEADING_TIMESTAMP_PATTERN = re.compile(
    r"^\s*\[(?P<minutes>\d{1,3}):(?P<seconds>\d{2}(?:\.\d{1,3})?)\]"
)

# <01:23.456>
INLINE_TIMESTAMP_PATTERN = re.compile(
    r"<\d{1,3}:\d{2}(?:\.\d{1,3})?>"
)

# [ti:Song], [ar:Artist], [offset:0], etc.
LRC_METADATA_PATTERN = re.compile(
    r"^\s*\[(ti|ar|al|by|offset|re|ve|length):[^\]]*\]\s*$",
    re.IGNORECASE
)

WHITESPACE_PATTERN = re.compile(r"[ \t\r\f\v]+")
REPEATED_LETTER_PATTERN = re.compile(r"([A-Za-z])\1{3,}", re.IGNORECASE)
REPEATED_EXCLAMATION_PATTERN = re.compile(r"!{4,}")
REPEATED_QUESTION_PATTERN = re.compile(r"\?{4,}")
REPEATED_PERIOD_PATTERN = re.compile(r"\.{4,}")


MUSIC_SYMBOLS = {
    "♪",
    "♫",
    "♬",
    "♩",
    "♭",
    "♮",
    "♯",
    "🎵",
    "🎶",
    "🎼"
}


DIRECT_REPLACEMENTS = {
    # Spaces
    "\u00A0": " ",
    "\u2007": " ",
    "\u202F": " ",
    "\u3000": " ",

    # Apostrophes
    "\u2018": "'",
    "\u2019": "'",
    "\u201A": "'",
    "\u201B": "'",
    "\u2032": "'",

    # Double quotes
    "\u201C": "\"",
    "\u201D": "\"",
    "\u201E": "\"",
    "\u201F": "\"",
    "\u2033": "\"",

    # Dashes
    "\u2010": "-",
    "\u2011": "-",
    "\u2012": "-",
    "\u2013": "-",
    "\u2014": "-",
    "\u2015": "-",
    "\u2212": "-",

    # Other punctuation
    "\u2026": "...",
    "\u060C": ",",
    "\u061F": "?",
    "\u00BF": "?",
    "\u00A1": "!",

    # Full-width punctuation
    "（": "(",
    "）": ")",
    "［": "[",
    "］": "]",
    "｛": "{",
    "｝": "}",
    "，": ",",
    "．": ".",
    "：": ":",
    "；": ";",
    "！": "!",
    "？": "?",
    "／": "/",
    "＼": "\\",
    "－": "-",
    "＿": "_",
    "＇": "'",
    "＂": "\""
}


SPECIAL_LATIN_REPLACEMENTS = {
    "ß": "ss",
    "ẞ": "SS",
    "æ": "ae",
    "Æ": "AE",
    "œ": "oe",
    "Œ": "OE",
    "ø": "o",
    "Ø": "O",
    "ł": "l",
    "Ł": "L",
    "ð": "d",
    "Ð": "D",
    "þ": "th",
    "Þ": "TH",
    "đ": "d",
    "Đ": "D",
    "ħ": "h",
    "Ħ": "H",
    "ı": "i",
    "ŋ": "n",
    "Ŋ": "N"
}


SUPPORTED_CHARACTERS = set(
    "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
    "abcdefghijklmnopqrstuvwxyz"
    "0123456789"
    " "
    "!\"#$%&'()*+,-./:;<=>?@[\\]^_`{|}~"
)


def is_invisible_formatting_character(character):
    if character == "\n":
        return False

    category = unicodedata.category(character)

    if category == "Cf":
        return True

    if category == "Cc" and character not in ["\t", "\n"]:
        return True

    codepoint = ord(character)

    if 0xFE00 <= codepoint <= 0xFE0F:
        return True

    if 0xE0100 <= codepoint <= 0xE01EF:
        return True

    return False


def strip_latin_accents(text):
    output = ""

    for character in text:
        if character in SPECIAL_LATIN_REPLACEMENTS:
            output += SPECIAL_LATIN_REPLACEMENTS[character]
            continue

        character_name = unicodedata.name(character, "")

        if "LATIN" in character_name:
            decomposed = unicodedata.normalize("NFKD", character)

            for decomposed_character in decomposed:
                if not unicodedata.combining(decomposed_character):
                    output += decomposed_character
        else:
            output += character

    return output


def cap_repeated_characters(text):
    def cap_letter_run(match):
        return match.group(0)[:3]

    text = REPEATED_LETTER_PATTERN.sub(cap_letter_run, text)
    text = REPEATED_EXCLAMATION_PATTERN.sub("!!!", text)
    text = REPEATED_QUESTION_PATTERN.sub("???", text)
    text = REPEATED_PERIOD_PATTERN.sub("...", text)

    return text


def replace_unsupported_runs(text):
    output = ""
    in_unsupported_run = False

    supported_visible_count = 0
    unsupported_visible_count = 0

    for character in text:
        if character in SUPPORTED_CHARACTERS:
            output += character
            in_unsupported_run = False

            if not character.isspace():
                supported_visible_count += 1

        elif character.isspace():
            output += " "
            in_unsupported_run = False

        else:
            unsupported_visible_count += 1

            if not in_unsupported_run:
                output += UNSUPPORTED_CHARACTER
                in_unsupported_run = True

    output = WHITESPACE_PATTERN.sub(" ", output).strip()

    return output, supported_visible_count, unsupported_visible_count


def clean_lyric_text(text):
    # Remove enhanced-LRC word timestamps if one ever appears.
    text = INLINE_TIMESTAMP_PATTERN.sub("", text)

    clean_characters = []

    for character in text:
        if not is_invisible_formatting_character(character):
            clean_characters.append(character)

    text = "".join(clean_characters)

    for original, replacement in DIRECT_REPLACEMENTS.items():
        text = text.replace(original, replacement)

    for music_symbol in MUSIC_SYMBOLS:
        text = text.replace(music_symbol, "")

    text = strip_latin_accents(text)
    text = cap_repeated_characters(text)
    text = WHITESPACE_PATTERN.sub(" ", text).strip()

    safe_text, supported_count, unsupported_count = replace_unsupported_runs(text)

    return safe_text, supported_count, unsupported_count


def scrub_synced_lyrics(raw_synced_lyrics):
    """
    Clean raw LRCLIB lyrics before caching them.

    Returns a dictionary containing:
        raw_synced_lyrics
        display_synced_lyrics
        display_status
        unsupported_ratio
        unsupported_line_count
        total_lyric_line_count
        scrub_version

    display_status may be:
        missing
        invalid_format
        unsupported_language
        partially_supported
        valid
    """

    # LRCLIB gave us no synced lyric data at all.
    if (
        raw_synced_lyrics is None
        or raw_synced_lyrics.strip() == ""
    ):
        return {
            "raw_synced_lyrics": raw_synced_lyrics,
            "display_synced_lyrics": None,
            "display_status": "missing",
            "unsupported_ratio": 0.0,
            "unsupported_line_count": 0,
            "total_lyric_line_count": 0,
            "scrub_version": SCRUB_VERSION
        }

    output_lines = []

    supported_visible_count = 0
    unsupported_visible_count = 0
    unsupported_line_count = 0

    for raw_line in raw_synced_lyrics.splitlines():

        # Ignore normal LRC metadata such as:
        # [ti:Song]
        # [ar:Artist]
        # [offset:0]
        if LRC_METADATA_PATTERN.match(raw_line):
            continue

        timestamp_match = LEADING_TIMESTAMP_PATTERN.match(
            raw_line
        )

        # Ignore lines that do not contain a valid leading timestamp.
        if timestamp_match is None:
            continue

        try:
            seconds = float(
                timestamp_match.group("seconds")
            )
        except ValueError:
            continue

        # Invalid LRC timestamp.
        if seconds >= 60:
            continue

        timestamp_text = (
            timestamp_match.group(0).strip()
        )

        lyric_text = raw_line[
            timestamp_match.end():
        ]

        (
            clean_text,
            line_supported_count,
            line_unsupported_count
        ) = clean_lyric_text(lyric_text)

        supported_visible_count += (
            line_supported_count
        )

        unsupported_visible_count += (
            line_unsupported_count
        )

        if line_unsupported_count > 0:
            unsupported_line_count += 1

        # Keep timed blank lines.
        #
        # These are meaningful because they intentionally
        # clear the LCD during instrumental sections.
        if clean_text == "":
            output_lines.append(timestamp_text)

        else:
            output_lines.append(
                timestamp_text + " " + clean_text
            )

    total_visible_count = (
        supported_visible_count
        + unsupported_visible_count
    )

    if total_visible_count == 0:
        unsupported_ratio = 0.0

    else:
        unsupported_ratio = (
            unsupported_visible_count
            / total_visible_count
        )

    # LRCLIB returned something, but we could not extract
    # even one usable timed lyric entry from it.
    if len(output_lines) == 0:
        display_status = "invalid_format"

    elif (
        unsupported_ratio
        > UNSUPPORTED_LANGUAGE_THRESHOLD
    ):
        display_status = "unsupported_language"

    elif (
        unsupported_ratio
        >= PARTIALLY_SUPPORTED_THRESHOLD
    ):
        display_status = "partially_supported"

    else:
        display_status = "valid"

    return {
        "raw_synced_lyrics": raw_synced_lyrics,
        "display_synced_lyrics": (
            "\n".join(output_lines)
        ),
        "display_status": display_status,
        "unsupported_ratio": round(
            unsupported_ratio,
            6
        ),
        "unsupported_line_count": (
            unsupported_line_count
        ),
        "total_lyric_line_count": len(
            output_lines
        ),
        "scrub_version": SCRUB_VERSION
    }


def create_lyrics_and_timestamp_lists(display_synced_lyrics):
    """
    Parse already scrubbed lyrics for playback.

    Returns:
        timestamp_list
        lyrics_list
    """

    timestamp_output = [0]
    lyrics_output = [""]

    if display_synced_lyrics is None:
        return timestamp_output, lyrics_output

    for line in display_synced_lyrics.splitlines():
        timestamp_match = LEADING_TIMESTAMP_PATTERN.match(line)

        if timestamp_match is None:
            continue

        try:
            minutes = int(timestamp_match.group("minutes"))
            seconds = float(timestamp_match.group("seconds"))

            if seconds >= 60:
                continue

            line_time_ms = int((minutes * 60 + seconds) * 1000)
            line_text = line[timestamp_match.end():].lstrip()

            timestamp_output.append(line_time_ms)
            lyrics_output.append(line_text)

        except ValueError:
            continue

    return timestamp_output, lyrics_output