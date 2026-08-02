import json
import time

import requests

from parser_v1 import (
    SCRUB_VERSION,
    scrub_synced_lyrics,
    create_lyrics_and_timestamp_lists
)
from spotify_handler import get_song_time


LRCLIB_URL = "https://lrclib.net/api/get"
CACHE_PATH = "cache/lyrics_cache.json"


lyrics_cache = {}


def get_lrclib_lyrics(params):
    if params is None:
        return None

    try:
        lrclib_response = requests.get(
            LRCLIB_URL,
            params=params,
            timeout=7
        )
    except requests.RequestException:
        return None

    if lrclib_response.status_code != 200:
        return None

    try:
        data = lrclib_response.json()
    except ValueError:
        return None

    return data.get("syncedLyrics")


def save_cache(cache_dict):
    with open(CACHE_PATH, "w", encoding="utf-8") as cache_file:
        json.dump(cache_dict, cache_file, indent=4)


def load_cache():
    global lyrics_cache

    try:
        with open(CACHE_PATH, "r", encoding="utf-8") as cache_file:
            lyrics_cache = json.load(cache_file)
    except FileNotFoundError:
        lyrics_cache = {}

    return lyrics_cache


def get_lyrics_from_cache(spotify_state):
    global lyrics_cache

    track_id = spotify_state["trackID"]
    track_data = lyrics_cache.get(track_id)

    return track_data


def save_lyrics_to_cache(spotify_state, raw_synced_lyrics):
    global lyrics_cache

    scrubbed_lyrics_data = scrub_synced_lyrics(raw_synced_lyrics)

    lyrics_cache[spotify_state["trackID"]] = {
        "track_name": spotify_state["trackName"],
        "artist_name": spotify_state["artistName"],
        "album_name": spotify_state["albumName"],
        "lrclib_album_name": spotify_state["albumName"],
        "duration_ms": spotify_state["durationMS"],
        "cached_at": time.time(),

        **scrubbed_lyrics_data
    }

    save_cache(lyrics_cache)

    return lyrics_cache[spotify_state["trackID"]]


def ensure_track_data_is_scrubbed(track_data):
    if track_data is None:
        return None

    updated_track_data = dict(track_data)

    # Convert old camelCase cache fields to snake_case.
    old_field_names = {
        "trackName": "track_name",
        "artistName": "artist_name",
        "albumName": "album_name",
        "lrclibAlbumName": "lrclib_album_name",
        "durationMS": "duration_ms",
        "cachedAt": "cached_at",
        "scrubVersion": "scrub_version",
        "rawSyncedLyrics": "raw_synced_lyrics",
        "displaySyncedLyrics": "display_synced_lyrics",
        "displayStatus": "display_status",
        "unsupportedRatio": "unsupported_ratio",
        "unsupportedLineCount": "unsupported_line_count",
        "totalLyricLineCount": "total_lyric_line_count"
    }

    for old_name, new_name in old_field_names.items():
        if old_name in updated_track_data:
            if new_name not in updated_track_data:
                updated_track_data[new_name] = updated_track_data[old_name]

            updated_track_data.pop(old_name)

    # Already scrubbed using the current format.
    if (
        updated_track_data.get("scrub_version") == SCRUB_VERSION
        and "display_synced_lyrics" in updated_track_data
    ):
        return updated_track_data

    raw_synced_lyrics = updated_track_data.get("raw_synced_lyrics")

    if raw_synced_lyrics is None:
        raw_synced_lyrics = updated_track_data.get("syncedLyrics")

    scrubbed_data = scrub_synced_lyrics(raw_synced_lyrics)

    updated_track_data.pop("syncedLyrics", None)
    updated_track_data.update(scrubbed_data)

    return updated_track_data


def midpoint(left, right):
    return left + (right - left) // 2


def get_current_lyric_index(timestamps, target):
    left = 0
    right = 0
    middle = 0
    best_index = 0

    right = len(timestamps) - 1
    middle = midpoint(left, right)

    while left <= right:
        middle = midpoint(left, right)
        current = timestamps[middle]

        if current <= target:
            best_index = middle
            left = middle + 1

        else:
            right = middle - 1

    return best_index


def load_lyrics_for_spotify_state(spotify_state):
    global lyrics_cache

    track_data = get_lyrics_from_cache(spotify_state)

    # Cached, check if scrubbed.
    if track_data is not None:
        scrubbed_track_data = ensure_track_data_is_scrubbed(track_data)

        if scrubbed_track_data != track_data:
            lyrics_cache[spotify_state["trackID"]] = scrubbed_track_data
            save_cache(lyrics_cache)

        track_data = scrubbed_track_data

        if track_data.get("display_status") == "missing":
            track_data = None

    # The song is not cached, so fetch and scrub it.
    if track_data is None:
        raw_synced_lyrics = get_lrclib_lyrics(
            spotify_state["lrclibParams"]
        )

        if raw_synced_lyrics is None:
            return [0], [""], 0, False

        track_data = save_lyrics_to_cache(
            spotify_state,
            raw_synced_lyrics
        )

    display_status = track_data.get("display_status", "valid")

    if display_status == "unsupported_language":
        return [0], ["I can't understand that yet!"], 0, True

    display_synced_lyrics = track_data.get("display_synced_lyrics")

    if display_synced_lyrics is None:
        return [0], [""], 0, False

    timestamp_list, lyrics_list = create_lyrics_and_timestamp_lists(
        display_synced_lyrics
    )

    current_lyric_index = get_current_lyric_index(
        timestamp_list,
        get_song_time(spotify_state)
    )

    return (
        timestamp_list,
        lyrics_list,
        current_lyric_index,
        True
    )