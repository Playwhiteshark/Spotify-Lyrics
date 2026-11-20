# Spotify Lyrics Display

## Optional idle auto-shutdown

Set `LYRICS_AUTO_SHUTDOWN_SECONDS` to a positive integer to choose the idle
shutdown delay in seconds. If it is unset, the display keeps the existing
3600-second default. Set it to `0` or `off` to disable automatic shutdown.

For a systemd service, automatic shutdown can be disabled with the drop-in
`/etc/systemd/system/lyrics-display.service.d/no-auto-shutdown.conf`:

```ini
[Service]
Environment=LYRICS_AUTO_SHUTDOWN_SECONDS=0
```
