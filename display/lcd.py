try:
    from RPLCD.i2c import CharLCD

    lcd = CharLCD(
        i2c_expander="PCF8574",
        address=0x27,
        port=1,
        cols=20,
        rows=4,
        charmap="A00"
    )

    LCD_AVAILABLE = True

except Exception as error:
    lcd = None
    LCD_AVAILABLE = False
    print(f"LCD unavailable; using console output only: {error}")


def write_lines_LCD(lines):
    if not LCD_AVAILABLE:
        return

    lcd.clear()

    for row, line in enumerate(lines[:4]):
        lcd.cursor_pos = (row, 0)
        lcd.write_string(line[:20].ljust(20))