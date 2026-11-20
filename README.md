# Spotify Lyrics Display

## Automatic shutdown

`LYRICS_AUTO_SHUTDOWN_SECONDS` controls automatic shutdowns:

- If unset, the display shuts down after one hour without playback or after five minutes when Spotify is unreachable.
- Set it to a positive integer to change the no-playback delay to that many seconds. The Spotify-unreachable delay remains five minutes.
- Set it to `0` or `off` (case-insensitive) to disable both automatic shutdown timers. Manual shutdown requests still work.
- Invalid values produce a warning and retain the default delays.

To disable automatic shutdown for the systemd service, create
`/etc/systemd/system/lyrics-display.service.d/no-auto-shutdown.conf` with:

```ini
[Service]
Environment=LYRICS_AUTO_SHUTDOWN_SECONDS=0
```

Then reload systemd and restart the service:

```sh
sudo systemctl daemon-reload
sudo systemctl restart lyrics-display.service
```
