# Spotify Lyrics

A Raspberry Pi karaoke display. It follows what you're playing on Spotify and shows the current line of synced lyrics on a 20×4 character LCD, kept in time with playback.

## How it works

- `spotify_handler.py` polls the Spotify Web API (`user-read-playback-state`) every 2 seconds for the current track and playback position.
- `lyrics_handler.py` fetches time-synced lyrics from [LRCLIB](https://lrclib.net) and caches them locally, so a song is only downloaded once.
- `parser_v1.py` cleans lyrics before caching them: it strips formatting characters, folds accents and replaces characters the LCD can't show. `cache_schema_reference.txt` documents the cache fields.
- `main.py` estimates the playback position between polls, resyncs when it drifts by more than 250 ms, and updates the display every 100 ms.
- `formatter.py` wraps each line to fit 4 rows × 20 columns, and `display/lcd.py` drives a PCF8574 I²C LCD. Without an LCD, output goes to the console, so you can develop on any machine.
- When nothing is playing, it shows rotating idle messages. After an hour idle, `power_control.py` shuts the Pi down.

## Hardware

- Raspberry Pi with network access
- 20×4 HD44780 character LCD with a PCF8574 I²C backpack (address `0x27`)

## Setup

1. Create an app in the [Spotify developer dashboard](https://developer.spotify.com/dashboard) and add `http://127.0.0.1:8888/callback` as a redirect URI.
2. Install dependencies:

   ```bash
   python3 -m venv .venv && source .venv/bin/activate
   pip install -r requirements.txt
   pip install RPLCD smbus2   # on the Pi, for the LCD
   ```

3. Copy `spotify_secrets_example.py` to `spotify_secrets.py` and fill in your client ID and secret. This file is gitignored.
4. Run `python main.py`. On first run, Spotify asks you to authorise. The token is cached in `.cache`, which is also gitignored.

Auto-shutdown runs `sudo /sbin/shutdown -h now`, so the user running the script needs passwordless sudo for that command.

## Customising idle messages

To use your own idle messages, create `idle_messages_local.py` (gitignored) that defines `IDLE_MESSAGES = [...]`. Otherwise the built-in defaults in `main.py` are used.

## License

MIT. See [LICENSE](LICENSE).
