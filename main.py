import time
import os
import logging

from spotify_handler import get_spotify_state, get_song_time

from lyrics_handler import (
    load_cache,
    load_lyrics_for_spotify_state,
    get_current_lyric_index
)

from display.display_handler import (
    display_text,
    update_display
)

from power_control import parse_auto_shutdown_seconds, shut_down_pi

from status.status_handler import (
    initialize_status_indicators,
    update_status_indicators,
    shutdown_status_indicators
)

display_text("Starting up...")


# ============ CONSTANTS ============

LYRIC_INTERVAL = 0.1      # 100 ms
SPOTIFY_INTERVAL = 2.0    # 2 seconds
TIME_RESYNC_THRESHOLD_MS = 250
LYRIC_RETRY_INTERVAL = 5.0
MAX_LYRIC_LOAD_ATTEMPTS = 6
NO_PLAYBACK_SHUTDOWN_DELAY, AUTO_SHUTDOWN_SETTING_VALID = (
    parse_auto_shutdown_seconds(
        os.getenv("LYRICS_AUTO_SHUTDOWN_SECONDS"),
        60 * 60
    )
)
SPOTIFY_UNREACHABLE_SHUTDOWN_DELAY = 5 * 60
IDLE_START_DELAY = 30.0
NOW_PLAYING_MIN_GAP_MS = 2000
NOW_PLAYING_MAX_DURATION_MS = 5000
SPOTIFY_RECONNECT_NOW_PLAYING_DELAY = 5.0

SHUTDOWN_REQUEST_PATH = "/tmp/lyrics-shutdown-requested"

if not AUTO_SHUTDOWN_SETTING_VALID:
    logging.warning(
        "Invalid LYRICS_AUTO_SHUTDOWN_SECONDS=%r; using default shutdown delays",
        os.getenv("LYRICS_AUTO_SHUTDOWN_SECONDS")
    )

# ============ VARIABLES ============

last_display_state = ""

# =========== FUNCTIONS ===========

def print_status_once(status_text):
    global last_display_state

    if status_text != last_display_state:
        print(status_text)
        last_display_state = status_text


def get_estimated_lyric_index(
    current_index,
    timestamps,
    current_time
):
    while (
        current_index > 0
        and current_time < timestamps[current_index]
    ):
        current_index -= 1

    while (
        current_index + 1 < len(timestamps)
        and current_time >= timestamps[current_index + 1]
    ):
        current_index += 1

    return current_index


def create_idle_state():
    return {
        "reason": None,
        "inactive_since": None,
        "is_idle": False,
        "shutdown_due": False
    }


def reset_idle_state(idle_state):
    idle_state["reason"] = None
    idle_state["inactive_since"] = None
    idle_state["is_idle"] = False
    idle_state["shutdown_due"] = False


def get_shutdown_delay(inactivity_reason):
    if NO_PLAYBACK_SHUTDOWN_DELAY is None:
        return None

    if inactivity_reason == "SPOTIFY_UNREACHABLE":
        return SPOTIFY_UNREACHABLE_SHUTDOWN_DELAY

    return NO_PLAYBACK_SHUTDOWN_DELAY


def update_idle_state(now, spotify_state, idle_state):
    inactivity_reason = get_inactivity_reason(spotify_state)

    # Playback is active
    if inactivity_reason is None:
        if idle_state["reason"] is not None:
            reset_idle_state(idle_state)
        return

    # We have entered inactivity, or the reason for inactivity changed
    if inactivity_reason != idle_state["reason"]:
        idle_state["reason"] = inactivity_reason
        idle_state["inactive_since"] = now
        idle_state["is_idle"] = False
        idle_state["shutdown_due"] = False

    inactive_time = now - idle_state["inactive_since"]

    idle_state["is_idle"] = (
        inactive_time >= IDLE_START_DELAY
    )

    shutdown_delay = get_shutdown_delay(
        idle_state["reason"]
    )

    idle_state["shutdown_due"] = (
        shutdown_delay is not None
        and inactive_time >= shutdown_delay
    )


def get_inactivity_reason(spotify_state):
    if (
        spotify_state["isValidTrack"]
        and spotify_state["isPlaying"]
    ):
        return None

    if spotify_state["stateType"] == "SPOTIFY_ERROR":
        return "SPOTIFY_UNREACHABLE"

    return "NO_PLAYBACK"


def create_empty_lyrics_state(track_id=None):
    return {
        "track_id": track_id,
        "timestamp_list": [0],
        "lyrics_list": [""],
        "current_lyric_index": 0,
        "has_lyrics": False,
        "lyric_load_attempts": 0,
        "next_lyric_retry_time": 0,
        "lyrics_retry_exhausted": False,
        "unavailable_reason": None,
        "now_playing_until": None
    }


def try_load_lyrics(spotify_state, lyrics_state):
    lyrics_state["lyric_load_attempts"] += 1

    (
        lyrics_state["timestamp_list"],
        lyrics_state["lyrics_list"],
        lyrics_state["current_lyric_index"],
        lyrics_state["has_lyrics"],
        lyrics_state["unavailable_reason"]
    ) = load_lyrics_for_spotify_state(spotify_state)

    return lyrics_state["has_lyrics"]


def update_lyric_progress(
    now,
    last_lyric_update,
    spotify_state,
    lyrics_state
):
    if (
        spotify_state["isValidTrack"] == False
        or lyrics_state["has_lyrics"] == False
    ):
        return last_lyric_update

    if now - last_lyric_update < LYRIC_INTERVAL:
        return last_lyric_update

    estimated_song_time_ms = get_song_time(spotify_state)

    # The temporary Now Playing period has finished.
    if (
        lyrics_state["now_playing_until"] is not None
        and estimated_song_time_ms
        >= lyrics_state["now_playing_until"]
    ):
        lyrics_state["now_playing_until"] = None

    lyrics_state["current_lyric_index"] = get_estimated_lyric_index(
        lyrics_state["current_lyric_index"],
        lyrics_state["timestamp_list"],
        estimated_song_time_ms
    )

    return now


def get_next_nonblank_lyric_time(lyrics_state):
    current_index = lyrics_state["current_lyric_index"]

    for index in range(
        current_index + 1,
        len(lyrics_state["lyrics_list"])
    ):
        if lyrics_state["lyrics_list"][index].strip() != "":
            return lyrics_state["timestamp_list"][index]

    return None


def prepare_now_playing(spotify_state, lyrics_state):
    lyrics_state["now_playing_until"] = None

    if (
        spotify_state["isValidTrack"] == False
        or spotify_state["isPlaying"] == False
        or lyrics_state["has_lyrics"] == False
    ):
        return

    current_lyric = lyrics_state["lyrics_list"][
        lyrics_state["current_lyric_index"]
    ]

    # Never cover an actual lyric with Now Playing.
    if current_lyric.strip() != "":
        return

    next_lyric_time = get_next_nonblank_lyric_time(
        lyrics_state
    )

    if next_lyric_time is None:
        return

    current_song_time = get_song_time(spotify_state)

    time_until_next_lyric = (
        next_lyric_time - current_song_time
    )

    if time_until_next_lyric >= NOW_PLAYING_MIN_GAP_MS:
        lyrics_state["now_playing_until"] = min(
            next_lyric_time,
            current_song_time + NOW_PLAYING_MAX_DURATION_MS
        )


def update_spotify_state(
    now,
    spotify_state,
    lyrics_state,
    idle_state
):
    old_spotify_state = spotify_state
    new_spotify_state = get_spotify_state()

    # Spotify currently has no valid track / cannot be reached
    if new_spotify_state["isValidTrack"] == False:
        print_status_once(new_spotify_state["stateType"])

        return new_spotify_state, lyrics_state

    # A genuinely different track is now playing
    if new_spotify_state["trackID"] != lyrics_state["track_id"]:
        spotify_state = new_spotify_state

        lyrics_state = create_empty_lyrics_state(
            new_spotify_state["trackID"]
        )

        # Clear any previous idle state before displaying the new track
        update_idle_state(
            now,
            spotify_state,
            idle_state
        )

        # Clear the previous song while lyric loading happens.
        display_text("")

        print_status_once("LOADING_LYRICS")

        if try_load_lyrics(spotify_state, lyrics_state):
            pass

        elif lyrics_state["unavailable_reason"] is not None:
            print_status_once(lyrics_state["unavailable_reason"])

        else:
            print_status_once("LYRICS_NOT_LOADED_RETRYING")

            lyrics_state["next_lyric_retry_time"] = (
                now + LYRIC_RETRY_INTERVAL
            )

        if lyrics_state["has_lyrics"]:
            prepare_now_playing(
                spotify_state,
                lyrics_state
            )

        return spotify_state, lyrics_state

    # From here onward, Spotify is reporting the same track.

    should_prepare_now_playing = False

    if new_spotify_state["isPlaying"]:

        # Paused track -> playing.
        if (
            old_spotify_state["isValidTrack"]
            and old_spotify_state["isPlaying"] == False
        ):
            should_prepare_now_playing = True

        # No playback/session -> same track playing again.
        elif (
            old_spotify_state["isValidTrack"] == False
            and idle_state["reason"] == "NO_PLAYBACK"
        ):
            should_prepare_now_playing = True

        # Spotify became reachable again after a meaningful outage.
        elif (
            old_spotify_state["isValidTrack"] == False
            and idle_state["reason"] == "SPOTIFY_UNREACHABLE"
            and idle_state["inactive_since"] is not None
            and (
                now - idle_state["inactive_since"]
                >= SPOTIFY_RECONNECT_NOW_PLAYING_DELAY
            )
        ):
            should_prepare_now_playing = True

    lyrics_loaded_this_update = False
    # Same track: retry lyrics if they have not loaded yet
    if (
        lyrics_state["has_lyrics"] == False
        and lyrics_state["lyrics_retry_exhausted"] == False
        and lyrics_state["unavailable_reason"] is None
        and now >= lyrics_state["next_lyric_retry_time"]
    ):
        print_status_once("RETRYING_LYRICS")

        if try_load_lyrics(new_spotify_state, lyrics_state):
            lyrics_loaded_this_update = True

        elif lyrics_state["unavailable_reason"] is not None:
            print_status_once(lyrics_state["unavailable_reason"])

        elif (
            lyrics_state["lyric_load_attempts"]
            >= MAX_LYRIC_LOAD_ATTEMPTS
        ):
            lyrics_state["lyrics_retry_exhausted"] = True
            print_status_once("LYRIC_RETRIES_EXHAUSTED")

        else:
            print_status_once("LYRICS_NOT_LOADED_RETRYING")

            lyrics_state["next_lyric_retry_time"] = (
                now + LYRIC_RETRY_INTERVAL
            )

    # Same track with lyrics: synchronize lyric position
    
    if lyrics_state["has_lyrics"]:
        actual_spotify_time_ms = get_song_time(
            new_spotify_state
        )

        if old_spotify_state["isValidTrack"]:

            # On resume, always use Spotify's actual position first.
            if should_prepare_now_playing:
                lyrics_state["current_lyric_index"] = (
                    get_current_lyric_index(
                        lyrics_state["timestamp_list"],
                        actual_spotify_time_ms
                    )
                )

            else:
                estimated_song_time_ms = get_song_time(
                    old_spotify_state
                )

                time_difference_ms = (
                    actual_spotify_time_ms
                    - estimated_song_time_ms
                )

                if (
                    abs(time_difference_ms)
                    > TIME_RESYNC_THRESHOLD_MS
                ):
                    print(
                        "Time jump detected:",
                        time_difference_ms,
                        "ms"
                    )

                    # A seek makes an old Now Playing period meaningless.
                    lyrics_state["now_playing_until"] = None

                    lyrics_state["current_lyric_index"] = (
                        get_current_lyric_index(
                            lyrics_state["timestamp_list"],
                            actual_spotify_time_ms
                        )
                    )

        else:
            # Same song returning after no valid Spotify state.
            lyrics_state["current_lyric_index"] = (
                get_current_lyric_index(
                    lyrics_state["timestamp_list"],
                    actual_spotify_time_ms
                )
            )

        # Don't let an expired Now Playing override survive.
        if (
            lyrics_state["now_playing_until"] is not None
            and actual_spotify_time_ms
            >= lyrics_state["now_playing_until"]
        ):
            lyrics_state["now_playing_until"] = None

    # Start/resume/reconnect, or lyrics finally arrived after retries.
    if (
        lyrics_state["has_lyrics"]
        and (
            should_prepare_now_playing
            or lyrics_loaded_this_update
        )
    ):
        prepare_now_playing(
            new_spotify_state,
            lyrics_state
        )

    return new_spotify_state, lyrics_state

def shutdown_requested():
    if not os.path.exists(SHUTDOWN_REQUEST_PATH):
        return False

    try:
        os.remove(SHUTDOWN_REQUEST_PATH)
    except OSError:
        pass

    return True

def perform_shutdown():
    display_text("Shutting down...\nSafe to unplug.")
    shutdown_status_indicators()
    shut_down_pi()

# =============== MAIN ===============


def main():

    initialize_status_indicators()

    spotify_state = get_spotify_state()

    load_cache()

    if spotify_state["isValidTrack"]:
        lyrics_state = create_empty_lyrics_state(
            spotify_state["trackID"]
        )
    else:
        lyrics_state = create_empty_lyrics_state()

    idle_state = create_idle_state()

    # If there is a session, say that lyrics are being loaded
    if spotify_state["isValidTrack"]:
        print_status_once("LOADING_LYRICS")

        # Try to get packaged lyrics from LRCLIB
        if try_load_lyrics(spotify_state, lyrics_state):
            prepare_now_playing(
                spotify_state,
                lyrics_state
            )

        elif lyrics_state["unavailable_reason"] is not None:
            print_status_once(lyrics_state["unavailable_reason"])

        else:
            print_status_once("LYRICS_NOT_LOADED_RETRYING")

            lyrics_state["next_lyric_retry_time"] = (
                time.perf_counter() + LYRIC_RETRY_INTERVAL
            )
    # Otherwise print what's happening.
    else:
        print_status_once(spotify_state["stateType"])

    last_lyric_update = time.perf_counter()
    last_spotify_check = time.perf_counter()

    while True:
        now = time.perf_counter()

        last_lyric_update = update_lyric_progress(
            now,
            last_lyric_update,
            spotify_state,
            lyrics_state
        )

        if now - last_spotify_check >= SPOTIFY_INTERVAL:
            spotify_state, lyrics_state = update_spotify_state(
                now,
                spotify_state,
                lyrics_state,
                idle_state
            )

            last_spotify_check = now

        update_idle_state(
            now,
            spotify_state,
            idle_state
        )

        update_status_indicators(
            now,
            spotify_state,
            lyrics_state,
            idle_state
        )

        if idle_state["shutdown_due"] or shutdown_requested():
            perform_shutdown()
            break

        update_display(
            now,
            spotify_state,
            lyrics_state,
            idle_state
        )

        time.sleep(0.01)


if __name__ == "__main__":
    main()
