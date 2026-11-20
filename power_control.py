import logging
import os
import subprocess


DEFAULT_AUTO_SHUTDOWN_SECONDS = 60 * 60


def parse_auto_shutdown_seconds(value):
    if value is None:
        return DEFAULT_AUTO_SHUTDOWN_SECONDS

    normalized_value = value.strip().lower()

    if normalized_value in ("0", "off"):
        return None

    if not normalized_value.isascii() or not normalized_value.isdecimal():
        raise ValueError("must be '0', 'off', or a positive integer")

    seconds = int(normalized_value)
    if seconds <= 0:
        raise ValueError("must be '0', 'off', or a positive integer")

    return seconds


def get_auto_shutdown_delay():
    value = os.getenv("LYRICS_AUTO_SHUTDOWN_SECONDS")

    try:
        return parse_auto_shutdown_seconds(value)
    except ValueError:
        logging.getLogger(__name__).warning(
            "Invalid LYRICS_AUTO_SHUTDOWN_SECONDS=%r; using default of %d seconds",
            value,
            DEFAULT_AUTO_SHUTDOWN_SECONDS
        )
        return DEFAULT_AUTO_SHUTDOWN_SECONDS


def shut_down_pi():
    subprocess.run(
        ["sudo", "/sbin/shutdown", "-h", "now"],
        check=True
    )
