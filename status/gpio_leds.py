from gpiozero import PWMLED


# BCM GPIO numbering
LED_PINS = {
    "on": 17,
    "idle": 27,
    "lyrics": 22
}


# Physical brightness calibration.
# Everything above this layer still thinks in terms of 0.0 -> 1.0.
LED_MAX_BRIGHTNESS = {
    "on": 1.0,
    "idle": 0.75,
    "lyrics": 1.0
}


# Blue track-change/resume flash.
FLASH_COUNT = 2
FLASH_OFF_TIME = 0.12
FLASH_ON_TIME = 0.12

# Yellow Spotify-unreachable blink.
BLINK_ON_TIME = 0.5
BLINK_OFF_TIME = 0.5


class StatusLED:

    def __init__(
        self,
        pin,
        max_brightness=1.0
    ):
        self.device = PWMLED(
            pin,
            frequency=1000
        )

        self.max_brightness = max_brightness

        # Normal state when no animation is overriding it.
        self.base_brightness = 0.0

        # Persistent blinking.
        self.is_blinking = False
        self.blink_started_at = None

        # Temporary flash animation.
        self.flash_started_at = None

        self.device.value = 0.0

    def set_brightness(self, brightness):
        self.base_brightness = max(
            0.0,
            min(1.0, brightness)
        )

    def set_on(self, is_on):
        self.set_brightness(
            1.0 if is_on else 0.0
        )

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

    def get_flash_brightness(self, now):
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

        # Start by switching off so a flash is
        # visible even if the LED was already solid.
        if cycle_position < FLASH_OFF_TIME:
            return 0.0

        return 1.0

    def get_blink_brightness(self, now):
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

        if cycle_position < BLINK_ON_TIME:
            return 1.0

        return 0.0

    def update(self, now):
        brightness = self.base_brightness

        blink_brightness = (
            self.get_blink_brightness(now)
        )

        if blink_brightness is not None:
            brightness = blink_brightness

        flash_brightness = (
            self.get_flash_brightness(now)
        )

        # Temporary flashes take priority over everything.
        if flash_brightness is not None:
            brightness = flash_brightness

        self.device.value = (
            brightness
            * self.max_brightness
        )

    def close(self):
        self.device.off()
        self.device.close()


class LEDController:

    def __init__(self):
        self.leds = {
            name: StatusLED(
                pin,
                LED_MAX_BRIGHTNESS[name]
            )
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