# Services

Five [runit](https://smarden.org/runit/) services and the boot script, as they run on the
phone. Install them into a service directory **of your own** (`~/pdata/sv`), never into
`$PREFIX/var/service` — see the pitfalls for the 22 minutes of CPU that lesson cost.

| Service | Runs as | Waits for |
|---|---|---|
| `bridge` | root | the CH340 to appear on the bus (one `grep` every 5 s) |
| `klippy` | root | the bridge's `~/printer` symlink, indefinitely |
| `moonraker` | root | the `klippy` socket, up to 90 s |
| `mainsail` | user | nothing — serves static files on `:8080` |
| `watchdog` | user | nothing — polls Moonraker every 15 s |

Each `log/run` sends the service's output to `svlogd` under `~/pdata/logs/sv-<service>/`, with
timestamps.

```bash
mkdir -p ~/pdata/sv
cp -r bridge klippy moonraker mainsail watchdog ~/pdata/sv/      # no supervise/ directories
cp boot.sh ~/.termux/boot/00-printer-stack.sh
chmod +x ~/.termux/boot/00-printer-stack.sh
runsvdir ~/pdata/sv &                                            # or reboot, with Termux:Boot installed
sv status ~/pdata/sv/*
```

The three root services record their real pid and forward `TERM` by hand, because `runsv`
cannot stop a process started through `su`. The `bridge` service expects the driver at
`~/ch341_pty.py`; `mainsail` and `watchdog` expect `~/serve_mainsail.py` and `~/watchdog.py`
from `scripts/`.
