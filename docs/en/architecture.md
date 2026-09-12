# Architecture

## The path, end to end

```
Ender 3 V3 SE mainboard (GD32F303 / STM32F103-compatible)
   │  USART1, 250000 baud
   ▼
CH340  (1a86:7523)  ── USB ──►  rooted Android phone (USB host)
                                   │
                                   │  /dev/bus/usb/BBB/DDD   (root)
                                   ▼
                            ch341_pty.py   ← the driver, pure Python
                                   │  USBDEVFS ioctls, no libusb
                                   ▼
                            pseudo-terminal  (/dev/pts/N)
                                   │  stable symlink: ~/printer
                                   ▼
                            klippy  ([mcu] serial: ~/printer)
                                   │  unix socket (~/pdata/run/klipper.sock)
                                   ▼
                            Moonraker  (0.0.0.0:7125)
                                   ▲
                            Mainsail (static files on :8080, talks to :7125 directly)
```

## Why each piece is there

**Why a driver of our own?** The Android kernel has no `ch341` module. Without it no Linux
process can get a `/dev/ttyUSB0`. The alternatives were: rebuild the kernel (one line in the
defconfig, but it needs a toolchain and flashing a boot image), use an external CDC-ACM
bridge (an ESP32-C3 or FTDI on the board's UART, which needs a part and soldering), or write
the driver. The third costs neither a part nor a kernel.

**Why USBDEVFS and not libusb/pyusb?** In Termux, libusb means building a native library and,
on the rootless path, depending on `termux-usb` to receive the descriptor. With root, talking
to `/dev/bus/usb/BBB/DDD` through `fcntl.ioctl` uses only the standard library and removes the
whole dependency.

**Why a pty?** Because Klipper opens `[mcu] serial:` as an ordinary serial device. The pty is
the adapter that makes the driver look like a serial port to everything above it. What it
cannot carry — parity, stop bits, DTR/RTS, hardware flow control — Klipper does not need.

**Why root?** Only for permission: `/dev/bus/usb` is `root:usb 0660`. Root does not create a
driver; it grants access to the node the driver talks through.

**Why do `klippy` and Moonraker also run as root?** Not by choice. With SELinux enforcing, the
bridge lives in the KernelSU domain and the pty it creates carries a label an app process
cannot open — `chcon` is refused even for root. The unix socket `klippy` serves is likewise
checked against the *server's* context. Whoever talks to `klippy` has to be in the same domain.
Mainsail's static server and the watchdog stay unprivileged: one only serves files, the other
talks TCP to Moonraker, and TCP is not subject to the restriction.

**Why a watchdog?** runit restarts processes that die. When the printer re-enumerates, the
bridge dies and comes back with a *new* pty — but `klippy` does not die; it keeps the old
descriptor and goes into `shutdown`. To the supervisor everything is up. The watchdog polls
the printer state through Moonraker and, on two consecutive bad readings, does the only
sequence that works: restart `klippy` (new pty), then `FIRMWARE_RESTART`.

**Why no nginx?** Termux's nginx does not link against the installed OpenSSL, and upgrading
OpenSSL risks `sshd`, the only way into the device. Mainsail talks to Moonraker directly
(`"hostname": null` in its `config.json`) and its files are served by a 12-line Tornado
script, using the Tornado already in Moonraker's virtualenv.

## The processes that stay up

| Service | User | Role |
|---|---|---|
| `bridge` | root | Holds the USB device and the pty. Waits for the CH340 before starting the driver |
| `klippy` | root | Opens `~/printer`. Waits for the symlink indefinitely |
| `moonraker` | root | API on `:7125`. Waits for the `klippy` socket |
| `mainsail` | user | Static files on `:8080` |
| `watchdog` | user | Polls `/printer/info` every 15 s; recovers a `klippy` stuck in `shutdown` |

Order matters: bridge first, then `klippy`, then Moonraker. Each `run` file waits for the
previous piece rather than failing and restarting, so an unplugged or switched-off printer
costs one `grep` every five seconds instead of a process per second.

The three root services record their real pid and forward `TERM` by hand, because `runsv`
cannot stop a process started through `su` — the signal stops at `su`.

## State on disk

```
~/printer                 symlink to the current pty (recreated by the bridge on every start)
~/pdata/config/           printer.cfg, moonraker.conf
~/pdata/run/              klipper.sock, klipper.tty, *.pid
~/pdata/logs/             klippy.log, moonraker.log, per-service svlogd directories
~/pdata/gcodes/           what Moonraker stores uploads in — and what [virtual_sdcard] must point at
~/pdata/sv/               the five runit services (a directory of our own, not $PREFIX/var/service)
~/.termux/boot/           the boot script, run by Termux:Boot
```
