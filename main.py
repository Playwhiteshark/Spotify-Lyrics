import time
import random

from spotify_handler import get_spotify_state, get_song_time

from lyrics_handler import (
    load_cache,
    load_lyrics_for_spotify_state,
    get_current_lyric_index
)

from formatter import format_text_to_bounds
from display.lcd import write_lines_LCD

# ============ CONSTANTS ============

LYRIC_INTERVAL = 0.1      # 100 ms
SPOTIFY_INTERVAL = 2.0    # 2 seconds
TIME_RESYNC_THRESHOLD_MS = 500
LYRIC_RETRY_INTERVAL = 5.0
MAX_LYRIC_LOAD_ATTEMPTS = 6
IDLE_MESSAGE_INTERVAL = 15.0
IDLE_START_DELAY = 30.0
IDLE_MESSAGES = [
    "Waiting...",
    "Nothing to sing yet.",
    "It says 'gullible' on the ceiling.",
    "Beware the Aydin curse.",
    "Play something!",
    "What if I don't like lyrics in my car?",
    "The Bertmobile karaoke system is idle.",
    "Have you heard of The Pigeons?",
    "Horrible nicknames like Adam Cheese and Uncle Taha...",
    "Lyrics machine is taking a nap.",
    "Welcome to the Bertmobile!",
    "Imagine a cool animation here.",
    "No bangers detected.",
    "It's like a fleck!",
    "I just an Eva...",
    "Watch Dexter!"
]

# ============ VARIABLES ============

last_display_state = ""
current_mode = "RUNNING"
idle_start_time = None
last_idle_message_time = 0
last_idle_message = ""

# =========== FUNCTIONS ===========

def print_status_once(status_text):
    global last_display_state

    if status_text != last_display_state:
        print(status_text)
        last_display_state = status_text


def get_estimated_lyric_index(current_index, timestamps, current_time):
    while (
        current_index + 1 < len(timestamps)
        and current_time >= timestamps[current_index + 1]
    ):
        current_index += 1

    return current_index


def should_be_idle(spotify_state, lyrics_state):
    if spotify_state["isValidTrack"] == False:
        return True

    if spotify_state["isPlaying"] == False:
        return True

    if lyrics_state["lyrics_failed_permanently"]:
        return True

    return False


def get_random_idle_message():
    global last_idle_message

    if len(IDLE_MESSAGES) == 1:
        chosen_message = IDLE_MESSAGES[0]
    else:
        possible_messages = []

        for message in IDLE_MESSAGES:
            if message != last_idle_message:
                possible_messages.append(message)

        chosen_message = random.choice(possible_messages)

    last_idle_message = chosen_message
    return chosen_message


def update_idle_mode(now, spotify_state, lyrics_state):
    global current_mode
    global idle_start_time
    global last_idle_message_time

    if should_be_idle(spotify_state, lyrics_state) == False:
        current_mode = "RUNNING"
        idle_start_time = None
        return

    if current_mode == "RUNNING":
        if idle_start_time is None:
            idle_start_time = now

        if now - idle_start_time >= IDLE_START_DELAY:
            current_mode = "IDLE"
            last_idle_message_time = now
            display_text(get_random_idle_message())

        return

    if now - last_idle_message_time >= IDLE_MESSAGE_INTERVAL:
        last_idle_message_time = now
        display_text(get_random_idle_message())


def print_lines(lines):
    print("")
    for line in lines:
        print(line)


def display_text(lyric):

    lines = format_text_to_bounds(lyric)

    # Display Lines
    print_lines(lines)
    write_lines_LCD(lines)

def create_empty_lyrics_state():
    return {
        "timestamp_list": [0],
        "lyrics_list": [""],
        "current_lyric_index": 0,
        "has_lyrics": False,
        "lyric_load_attempts": 0,
        "next_lyric_retry_time": 0,
        "lyrics_failed_permanently": False
    }

def try_load_lyrics(spotify_state, lyrics_state):
    lyrics_state["lyric_load_attempts"] += 1

    (
        lyrics_state["timestamp_list"],
        lyrics_state["lyrics_list"],
        lyrics_state["current_lyric_index"],
        lyrics_state["has_lyrics"]
    ) = load_lyrics_for_spotify_state(spotify_state)

    if lyrics_state["has_lyrics"]:
        display_text(
            lyrics_state["lyrics_list"][
                lyrics_state["current_lyric_index"]
            ]
        )

    return lyrics_state["has_lyrics"]


# =============== MAIN ===============
def main():
    display_text("Starting up...")

    spotify_state = get_spotify_state()
    # Key = trackID, data is another dict containing lyrics only for now,
    # but can contain other stuff
    load_cache()

    lyrics_state = create_empty_lyrics_state()

    # If there is a session, say that lyrics are being loaded
    if spotify_state["isValidTrack"]:
        print_status_once("LOADING_LYRICS")

        # Try to get packaged lyrics from LRCLIB
        if try_load_lyrics(spotify_state, lyrics_state):
            pass
        else:  # If no lyrics, print that you're retrying, then retry later.
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
        
        update_idle_mode(
            now,
            spotify_state,
            lyrics_state
        )

        if spotify_state["isValidTrack"] and lyrics_state["has_lyrics"]:
            estimated_song_time_ms = get_song_time(spotify_state)

            if now - last_lyric_update >= LYRIC_INTERVAL:
                original_lyric_index = lyrics_state["current_lyric_index"]
                lyrics_state["current_lyric_index"] = get_estimated_lyric_index(
                    lyrics_state["current_lyric_index"],
                    lyrics_state["timestamp_list"],
                    estimated_song_time_ms
                )

                if original_lyric_index != lyrics_state["current_lyric_index"]:
                    display_text(lyrics_state["lyrics_list"][lyrics_state["current_lyric_index"]])

                last_lyric_update = now

        if now - last_spotify_check >= SPOTIFY_INTERVAL:
            old_spotify_state = spotify_state
            new_spotify_state = get_spotify_state()

            if new_spotify_state["isValidTrack"] == False:
                spotify_state = new_spotify_state
                lyrics_state = create_empty_lyrics_state()

                print_status_once(spotify_state["stateType"])

            elif (
                old_spotify_state["isValidTrack"] == False
                or new_spotify_state["trackID"] != old_spotify_state["trackID"]
            ):
                spotify_state = new_spotify_state

                lyrics_state = create_empty_lyrics_state()

                print_status_once("LOADING_LYRICS")

                if try_load_lyrics(spotify_state, lyrics_state):
                    pass
                else:
                    print_status_once("LYRICS_NOT_LOADED_RETRYING")
                    lyrics_state["next_lyric_retry_time"] = (
                        time.perf_counter() + LYRIC_RETRY_INTERVAL
                    )

            else:
                if lyrics_state["has_lyrics"] == False and lyrics_state["lyrics_failed_permanently"] == False:
                    if now >= lyrics_state["next_lyric_retry_time"]:
                        print_status_once("RETRYING_LYRICS")

                        if try_load_lyrics(new_spotify_state, lyrics_state):
                            pass

                        elif lyrics_state["lyric_load_attempts"] >= MAX_LYRIC_LOAD_ATTEMPTS:
                            lyrics_state["lyrics_failed_permanently"] = True
                            print_status_once("NO_SYNCED_LYRICS")

                        else:
                            print_status_once("LYRICS_NOT_LOADED_RETRYING")
                            lyrics_state["next_lyric_retry_time"] = (
                                now + LYRIC_RETRY_INTERVAL
                            )

                estimated_song_time_ms = get_song_time(spotify_state)
                actual_spotify_time_ms = get_song_time(new_spotify_state)
                time_difference_ms = (
                    actual_spotify_time_ms - estimated_song_time_ms
                )

                if (
                    lyrics_state["has_lyrics"]
                    and abs(time_difference_ms) > TIME_RESYNC_THRESHOLD_MS
                ):
                    print("Time jump detected:", time_difference_ms, "ms")

                    lyrics_state["current_lyric_index"] = get_current_lyric_index(
                        lyrics_state["timestamp_list"],
                        actual_spotify_time_ms
                    )
                    display_text(lyrics_state["lyrics_list"][lyrics_state["current_lyric_index"]])

                spotify_state = new_spotify_state

            last_spotify_check = now

        time.sleep(0.01)


if __name__ == "__main__":
    main()