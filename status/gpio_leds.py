from gpiozero import PWMLED


# BCM GPIO numbering
LED_PINS = {
    "on": 17,
    "idle": 27,
    "lyrics": 22
}


class StatusLED:

    def __init__(self, pin):
        self.device = PWMLED(pin)

        self.mode = "steady"
        self.brightness = 0.0

        # Reserved for future animations.
        self.animation_started_at = None

        self.device.value = 0.0

    def set_brightness(self, brightness):
        brightness = max(
            0.0,
            min(1.0, brightness)
        )

        self.mode = "steady"
        self.brightness = brightness
        self.animation_started_at = None

        self.device.value = brightness

    def set_on(self, is_on):
        if is_on:
            self.set_brightness(1.0)
        else:
            self.set_brightness(0.0)

    def update(self, now):
        """
        Animation updates will eventually happen here.

        For now all LEDs are steady, so there is
        nothing to update every frame.
        """
        pass

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

    def set_active_indicators(self, active_indicators):
        active_indicators = set(active_indicators)

        # Don't continually rewrite LEDs if nothing changed.
        if active_indicators == self.active_indicators:
            return

        self.active_indicators = active_indicators

        for name, led in self.leds.items():
            led.set_on(
                name in active_indicators
            )

    def update(self, now):
        for led in self.leds.values():
            led.update(now)

    def close(self):
        for led in self.leds.values():
            led.close()