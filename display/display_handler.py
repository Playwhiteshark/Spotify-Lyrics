from formatter import format_text_to_bounds
from display.lcd import write_lines_LCD


last_display_lines = None


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