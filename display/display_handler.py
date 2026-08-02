import random

from formatter import format_text_to_bounds
from display.lcd import write_lines_LCD

IDLE_MESSAGE_INTERVAL = 15.0
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
    "Watch Dexter!",
    "It's never Lupus.",
    "That's way too far...",
    "Are you five years old?"
]


last_display_lines = None

last_idle_message_time = 0
last_idle_message = ""


def display_text(text):
    global last_display_lines

    lines = format_text_to_bounds(text)

    if lines == last_display_lines:
        return

    last_display_lines = lines

    print("")
    for line in lines:
        print(line)

    write_lines_LCD(lines)


def display_now_playing(spotify_state):
    display_text(
        "NOW PLAYING:\n"
        f"{spotify_state['trackName']}\n"
        f"{spotify_state['artistName']}"
    )


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


def update_idle_display(now, idle_state):
    global last_idle_message_time

    if idle_state["is_idle"] == False:
        last_idle_message_time = 0
        return

    if (
        last_idle_message_time == 0
        or now - last_idle_message_time >= IDLE_MESSAGE_INTERVAL
    ):
        last_idle_message_time = now
        display_text(get_random_idle_message())
