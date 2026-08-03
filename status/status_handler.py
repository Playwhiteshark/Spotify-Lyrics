STATUS_LEDS_ENABLED = True

led_controller = None


def initialize_status_indicators():
    global led_controller

    if not STATUS_LEDS_ENABLED:
        return

    try:
        from status.gpio_leds import LEDController

        led_controller = LEDController()

    except (ImportError, OSError) as error:
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


def update_status_indicators(
    now,
    spotify_state,
    lyrics_state,
    idle_state
):
    if led_controller is None:
        return

    active_indicators = get_active_indicators(
        spotify_state,
        lyrics_state,
        idle_state
    )

    led_controller.set_active_indicators(
        active_indicators
    )

    led_controller.update(now)


def shutdown_status_indicators():
    global led_controller

    if led_controller is None:
        return

    led_controller.close()
    led_controller = None