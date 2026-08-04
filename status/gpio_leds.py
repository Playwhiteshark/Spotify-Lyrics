from gpiozero import LED


# BCM GPIO numbering
LED_PINS = {
    "on": 17,
    "idle": 27,
    "lyrics": 22
}


# Blue track-change/resume flash.
FLASH_COUNT = 2
FLASH_OFF_TIME = 0.12
FLASH_ON_TIME = 0.12

# Yellow Spotify-unreachable blink.
BLINK_ON_TIME = 0.5
BLINK_OFF_TIME = 0.5


class StatusLED:

    def __init__(self, pin):
        self.device = LED(pin)

        # Normal state when no animation is overriding it.
        self.base_on = False

        # Persistent blinking.
        self.is_blinking = False
        self.blink_started_at = None

        # Temporary flash animation.
        self.flash_started_at = None

        self.device.off()

    def set_on(self, is_on):
        self.base_on = is_on

    def set_blinking(
        self,
        enabled,
        now
    ):
        if enabled:
            if not self.is_blinking:
                self.is_blinking = True
                self.blink_started_at = now

        else:
            self.is_blinking = False
            self.blink_started_at = None

    def flash(self, now):
        self.flash_started_at = now

    def get_flash_state(self, now):
        if self.flash_started_at is None:
            return None

        elapsed = (
            now - self.flash_started_at
        )

        cycle_duration = (
            FLASH_OFF_TIME
            + FLASH_ON_TIME
        )

        total_duration = (
            cycle_duration
            * FLASH_COUNT
        )

        if elapsed >= total_duration:
            self.flash_started_at = None
            return None

        cycle_position = (
            elapsed % cycle_duration
        )

        # Start OFF so the flash is visible even if
        # the LED was already steadily on.
        if cycle_position < FLASH_OFF_TIME:
            return False

        return True

    def get_blink_state(self, now):
        if (
            not self.is_blinking
            or self.blink_started_at is None
        ):
            return None

        elapsed = (
            now - self.blink_started_at
        )

        cycle_duration = (
            BLINK_ON_TIME
            + BLINK_OFF_TIME
        )

        cycle_position = (
            elapsed % cycle_duration
        )

        return cycle_position < BLINK_ON_TIME

    def update(self, now):
        is_on = self.base_on

        blink_state = (
            self.get_blink_state(now)
        )

        if blink_state is not None:
            is_on = blink_state

        flash_state = (
            self.get_flash_state(now)
        )

        # Temporary flash takes priority over blinking
        # and the normal steady state.
        if flash_state is not None:
            is_on = flash_state

        self.device.value = is_on

    def close(self):
        self.device.off()
        self.device.close()


class LEDController:

    def __init__(self):
        self.leds = {
            name: StatusLED(pin)
            for name, pin in LED_PINS.items()
        }

        self.active_indicators = set()

    def set_active_indicators(
        self,
        active_indicators
    ):
        active_indicators = set(
            active_indicators
        )

        if (
            active_indicators
            == self.active_indicators
        ):
            return

        self.active_indicators = (
            active_indicators
        )

        for name, led in self.leds.items():
            led.set_on(
                name in active_indicators
            )

    def flash_indicator(
        self,
        name,
        now
    ):
        self.leds[name].flash(now)

    def set_indicator_blinking(
        self,
        name,
        enabled,
        now
    ):
        self.leds[name].set_blinking(
            enabled,
            now
        )

    def update(self, now):
        for led in self.leds.values():
            led.update(now)

    def close(self):
        for led in self.leds.values():
            led.close()