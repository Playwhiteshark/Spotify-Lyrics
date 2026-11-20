import subprocess


def parse_auto_shutdown_seconds(value, default_seconds):
    if value is None:
        return default_seconds, True

    normalized_value = value.strip()

    if normalized_value == "0" or normalized_value.lower() == "off":
        return None, True

    try:
        seconds = int(normalized_value)
    except ValueError:
        return default_seconds, False

    if seconds > 0:
        return seconds, True

    return default_seconds, False


def shut_down_pi():
    subprocess.run(
        ["sudo", "/sbin/shutdown", "-h", "now"],
        check=True
    )
    
