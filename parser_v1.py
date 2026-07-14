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


SCRUB_VERSION = 1

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


def IsInvisibleFormattingCharacter(character):
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


def StripLatinAccents(text):
    output = ""

    for character in text:
        if character in SPECIAL_LATIN_REPLACEMENTS:
            output += SPECIAL_LATIN_REPLACEMENTS[character]
            continue

        characterName = unicodedata.name(character, "")

        if "LATIN" in characterName:
            decomposed = unicodedata.normalize("NFKD", character)

            for decomposedCharacter in decomposed:
                if not unicodedata.combining(decomposedCharacter):
                    output += decomposedCharacter
        else:
            output += character

    return output


def CapRepeatedCharacters(text):
    def CapLetterRun(match):
        return match.group(0)[:3]

    text = REPEATED_LETTER_PATTERN.sub(CapLetterRun, text)
    text = REPEATED_EXCLAMATION_PATTERN.sub("!!!", text)
    text = REPEATED_QUESTION_PATTERN.sub("???", text)
    text = REPEATED_PERIOD_PATTERN.sub("...", text)

    return text


def ReplaceUnsupportedRuns(text):
    output = ""
    inUnsupportedRun = False

    supportedVisibleCount = 0
    unsupportedVisibleCount = 0

    for character in text:
        if character in SUPPORTED_CHARACTERS:
            output += character
            inUnsupportedRun = False

            if not character.isspace():
                supportedVisibleCount += 1

        elif character.isspace():
            output += " "
            inUnsupportedRun = False

        else:
            unsupportedVisibleCount += 1

            if not inUnsupportedRun:
                output += UNSUPPORTED_CHARACTER
                inUnsupportedRun = True

    output = WHITESPACE_PATTERN.sub(" ", output).strip()

    return output, supportedVisibleCount, unsupportedVisibleCount


def CleanLyricText(text):
    # Remove enhanced-LRC word timestamps if one ever appears.
    text = INLINE_TIMESTAMP_PATTERN.sub("", text)

    cleanCharacters = []

    for character in text:
        if not IsInvisibleFormattingCharacter(character):
            cleanCharacters.append(character)

    text = "".join(cleanCharacters)

    for original, replacement in DIRECT_REPLACEMENTS.items():
        text = text.replace(original, replacement)

    for musicSymbol in MUSIC_SYMBOLS:
        text = text.replace(musicSymbol, "")

    text = StripLatinAccents(text)
    text = CapRepeatedCharacters(text)
    text = WHITESPACE_PATTERN.sub(" ", text).strip()

    safeText, supportedCount, unsupportedCount = ReplaceUnsupportedRuns(text)

    return safeText, supportedCount, unsupportedCount


def ScrubSyncedLyrics(rawSyncedLyrics):
    """
    Clean raw LRCLIB lyrics before caching them.

    Returns a dictionary containing:
        rawSyncedLyrics
        displaySyncedLyrics
        displayStatus
        unsupportedRatio
        unsupportedLineCount
        totalLyricLineCount
        scrubVersion
    """

    if rawSyncedLyrics is None:
        return {
            "rawSyncedLyrics": None,
            "displaySyncedLyrics": None,
            "displayStatus": "missing",
            "unsupportedRatio": 0.0,
            "unsupportedLineCount": 0,
            "totalLyricLineCount": 0,
            "scrubVersion": SCRUB_VERSION
        }

    outputLines = []

    supportedVisibleCount = 0
    unsupportedVisibleCount = 0
    unsupportedLineCount = 0

    for rawLine in rawSyncedLyrics.splitlines():
        # Remove LRC metadata such as [ti:], [ar:] and [offset:].
        if LRC_METADATA_PATTERN.match(rawLine):
            continue

        timestampMatch = LEADING_TIMESTAMP_PATTERN.match(rawLine)

        if timestampMatch is None:
            # Ignore malformed non-timed lines rather than caching them as lyrics.
            continue

        seconds = float(timestampMatch.group("seconds"))

        if seconds >= 60:
            continue

        timestampText = timestampMatch.group(0).strip()
        lyricText = rawLine[timestampMatch.end():]

        cleanText, lineSupportedCount, lineUnsupportedCount = CleanLyricText(
            lyricText
        )

        supportedVisibleCount += lineSupportedCount
        unsupportedVisibleCount += lineUnsupportedCount

        if lineUnsupportedCount > 0:
            unsupportedLineCount += 1

        # Preserve the timestamp even when the lyric is blank.
        if cleanText == "":
            outputLines.append(timestampText)
        else:
            outputLines.append(timestampText + " " + cleanText)

    totalVisibleCount = supportedVisibleCount + unsupportedVisibleCount

    if totalVisibleCount == 0:
        unsupportedRatio = 0.0
    else:
        unsupportedRatio = unsupportedVisibleCount / totalVisibleCount

    if unsupportedRatio > UNSUPPORTED_LANGUAGE_THRESHOLD:
        displayStatus = "unsupported_language"
    elif unsupportedRatio >= PARTIALLY_SUPPORTED_THRESHOLD:
        displayStatus = "partially_supported"
    else:
        displayStatus = "valid"

    return {
        "rawSyncedLyrics": rawSyncedLyrics,
        "displaySyncedLyrics": "\n".join(outputLines),
        "displayStatus": displayStatus,
        "unsupportedRatio": round(unsupportedRatio, 6),
        "unsupportedLineCount": unsupportedLineCount,
        "totalLyricLineCount": len(outputLines),
        "scrubVersion": SCRUB_VERSION
    }


def CreateLyricsAndTimestampLists(displaySyncedLyrics):
    """
    Parse already scrubbed lyrics for playback.

    Returns:
        timestampList
        lyricsList
    """

    timestampOutput = [0]
    lyricsOutput = [""]

    if displaySyncedLyrics is None:
        return timestampOutput, lyricsOutput

    for line in displaySyncedLyrics.splitlines():
        timestampMatch = LEADING_TIMESTAMP_PATTERN.match(line)

        if timestampMatch is None:
            continue

        try:
            minutes = int(timestampMatch.group("minutes"))
            seconds = float(timestampMatch.group("seconds"))

            if seconds >= 60:
                continue

            lineTimeMS = int((minutes * 60 + seconds) * 1000)
            lineText = line[timestampMatch.end():].lstrip()

            timestampOutput.append(lineTimeMS)
            lyricsOutput.append(lineText)

        except ValueError:
            continue

    return timestampOutput, lyricsOutput