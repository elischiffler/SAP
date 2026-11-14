"""Priority-5-only LED adapter for the Pi polling loop (no GPIO import required)."""


def update_led(led, status):
    """Apply each successful /status response; pass None on failed polls.

    Never use queue size, button presses, or connectivity to light this LED.
    Strict bool checking prevents malformed truthy values from lighting it.
    """
    if isinstance(status, dict) and status.get("led_on") is True:
        led.on()
    else:
        led.off()
