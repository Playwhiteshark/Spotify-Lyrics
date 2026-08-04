import time

import spotipy
from spotipy.oauth2 import SpotifyOAuth


try:
    from spotify_secrets import SPOTIPY_CLIENT_ID, SPOTIPY_CLIENT_SECRET
except ImportError:
    raise ImportError(
        "Missing spotify_secrets.py. Copy spotify_secrets_example.py, "
        "rename it to spotify_secrets.py, and add your Spotify client ID and secret."
    )


SPOTIPY_REDIRECT_URI = "http://127.0.0.1:8888/callback"
SCOPE = "user-read-playback-state"

DELAY_FILE_PATH = "/home/ahmed/.lyrics-display-delay-ms"
DELAY_REFRESH_INTERVAL = 0.1

_cached_lyric_delay_ms = 0
_last_delay_check = 0.0


sp_auth = SpotifyOAuth(
    client_id=SPOTIPY_CLIENT_ID,
    client_secret=SPOTIPY_CLIENT_SECRET,
    redirect_uri=SPOTIPY_REDIRECT_URI,
    scope=SCOPE
)

sp = spotipy.Spotify(auth_manager=sp_auth)


def get_invalid_spotify_state(state_type, error=None):
    return {
        "stateType": state_type,
        "isValidTrack": False,
        "trackID": None,
        "artistName": None,
        "trackName": None,
        "albumName": None,
        "durationMS": 0,
        "durationS": 0,
        "progressMS": 0,
        "requestTime": time.perf_counter(),
        "isPlaying": False,
        "lrclibParams": None,
        "error": error
    }


def get_spotify_state():
    try:
        current = sp.current_playback()
    except Exception as error:
        return get_invalid_spotify_state("SPOTIFY_ERROR", error)

    if current is None:
        return get_invalid_spotify_state("NO_ACTIVE_SESSION")

    item = current.get("item")

    if item is None:
        return get_invalid_spotify_state("NO_ITEM")

    if item.get("type") != "track":
        return get_invalid_spotify_state("NOT_TRACK")

    try:
        artist_name = item["artists"][0]["name"]
        track_name = item.get("name")
        album_name = item.get("album")["name"]
        duration_ms = item["duration_ms"]

        # SPOTIFYSTATE FORMAT:
        return {
            "stateType": "TRACK",
            "isValidTrack": True,
            "trackID": item["id"],
            "artistName": artist_name,
            "trackName": track_name,
            "albumName": album_name,
            "durationMS": duration_ms,
            "durationS": duration_ms // 1000,
            "progressMS": current.get("progress_ms"),
            "requestTime": time.perf_counter(),
            "isPlaying": current.get("is_playing"),

            "lrclibParams": {
                "artist_name": artist_name,
                "track_name": track_name,
                "album_name": album_name,
                "duration": duration_ms // 1000
            },
            "error": None
        }

    except Exception as error:
        return get_invalid_spotify_state("BAD_TRACK_DATA", error)


def get_lyric_delay_ms():
    global _cached_lyric_delay_ms
    global _last_delay_check

    now = time.perf_counter()

    if (
        now - _last_delay_check
        < DELAY_REFRESH_INTERVAL
    ):
        return _cached_lyric_delay_ms

    _last_delay_check = now

    try:
        with open(
            DELAY_FILE_PATH,
            "r",
            encoding="utf-8"
        ) as delay_file:
            _cached_lyric_delay_ms = int(
                delay_file.read().strip()
            )

    except (FileNotFoundError, ValueError, OSError):
        _cached_lyric_delay_ms = 0

    return _cached_lyric_delay_ms


def get_song_time(spotify_state):
    if spotify_state["isPlaying"] == False:
        song_time_ms = spotify_state["progressMS"]

    else:
        elapsed_ms = (
            time.perf_counter()
            - spotify_state["requestTime"]
        ) * 1000

        song_time_ms = (
            spotify_state["progressMS"]
            + elapsed_ms
        )

    lyric_delay_ms = get_lyric_delay_ms()

    return max(
        0,
        song_time_ms - lyric_delay_ms
    )