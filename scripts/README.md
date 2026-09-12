# Scripts

| | |
|---|---|
| `watchdog.py` | The fifth service. Polls `/printer/info` on Moonraker; after two consecutive `shutdown`/`error` readings it restarts `klippy` (to pick up the new pty) and then issues `FIRMWARE_RESTART`. That order is the only one that works |
| `serve_mainsail.py` | Twelve lines of Tornado serving Mainsail's static files on `:8080` with SPA fallback, because Termux's nginx does not link |
| `klipctl.py` | Sends a request to `klippy`'s API socket directly. `python klipctl.py "G28"` runs a gcode and waits; `send("info")` from Python answers the "is it actually connected?" question the log cannot |

The driver itself is not here — it is
[`ch341-userspace-pty`](https://github.com/ivesiure/ch341-userspace-pty), and the licence split
is deliberate.
