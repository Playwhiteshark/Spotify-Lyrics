STATUS_LEDS_ENABLED = True

led_controller = None

last_track_id = None
last_is_playing = False
playback_state_initialized = False


def initialize_status_indicators():
    global led_controller

    if not STATUS_LEDS_ENABLED:
        return

    try:
        from status.gpio_leds import LEDController

        led_controller = LEDController()

    except Exception as error:
        print(
            "Status LEDs could not be initialized:",
            error
        )

        led_controller = None
        return

    # The program is now running.
    led_controller.set_active_indicators({
        "on"
    })


def get_active_indicators(
    spotify_state,
    lyrics_state,
    idle_state
):
    active_indicators = {
        "on"
    }

    if idle_state["is_idle"]:
        active_indicators.add(
            "idle"
        )

    if (
        spotify_state["isValidTrack"]
        and spotify_state["isPlaying"]
        and lyrics_state["has_lyrics"]
    ):
        active_indicators.add(
            "lyrics"
        )

    return active_indicators


def should_flash_lyrics_indicator(
    spotify_state
):
    global last_track_id
    global last_is_playing
    global playback_state_initialized

    is_valid_track = (
        spotify_state["isValidTrack"]
    )

    is_playing = (
        is_valid_track
        and spotify_state["isPlaying"]
    )

    current_track_id = (
        spotify_state["trackID"]
        if is_valid_track
        else None
    )

    # Establish the initial playback state without
    # flashing when the program first starts.
    if not playback_state_initialized:
        last_track_id = current_track_id
        last_is_playing = is_playing
        playback_state_initialized = True
        return False

    track_changed = (
        current_track_id is not None
        and last_track_id is not None
        and current_track_id != last_track_id
    )

    playback_resumed = (
        current_track_id is not None
        and current_track_id == last_track_id
        and is_playing
        and not last_is_playing
    )

    # Keep the last known valid track so a temporary
    # Spotify outage does not erase track identity.
    if current_track_id is not None:
        last_track_id = current_track_id

    last_is_playing = is_playing

    return (
        track_changed
        or playback_resumed
    )


def update_status_indicators(
    now,
    spotify_state,
    lyrics_state,
    idle_state
):
    if led_controller is None:
        return

    active_indicators = (
        get_active_indicators(
            spotify_state,
            lyrics_state,
            idle_state
        )
    )

    led_controller.set_active_indicators(
        active_indicators
    )

    # Blue: quick double flash on track change/resume.
    if should_flash_lyrics_indicator(
        spotify_state
    ):
        led_controller.flash_indicator(
            "lyrics",
            now
        )

    # Yellow: blink while Spotify cannot be reached.
    spotify_unreachable = (
        idle_state["reason"]
        == "SPOTIFY_UNREACHABLE"
    )

    led_controller.set_indicator_blinking(
        "idle",
        spotify_unreachable,
        now
    )

    led_controller.update(now)


def shutdown_status_indicators():
    global led_controller
    global last_track_id
    global last_is_playing
    global playback_state_initialized

    if led_controller is not None:
        led_controller.close()

    led_controller = None

    last_track_id = None
    last_is_playing = False
    playback_state_initialized = False