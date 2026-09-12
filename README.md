# Klipper on a rooted Android phone

Running the **Klipper host** (`klippy`, Moonraker and Mainsail) on a **rooted Android phone**,
connected over USB to an **Ender 3 V3 SE** — a printer whose mainboard talks through a
**CH340** USB-serial chip that the Android kernel has no driver for.

This repository is the part that is *not* the driver: the recipe, the service layout, the two
patches Klipper needs on Android, and above all the **pitfalls** — the list of ways this setup
fails silently or points the diagnosis in the wrong direction. The driver itself lives in its
own repository, [`ch341-userspace-pty`](https://github.com/ivesiure/ch341-userspace-pty).

> **Português:** [README.pt-BR.md](README.pt-BR.md) — the whole documentation is also
> available in `docs/pt-BR/`.

## Why this exists

Every "Klipper on Android" guide solves the serial port the same way: install
[Octo4a](https://github.com/feelfreelinux/octo4a) — a complete OctoPrint server in Java — only
to borrow its serial driver, and point `[mcu] serial:` at its `serialpipe`. With a CH340 board
that path fails at the very first handshake, and the open issues about it were never resolved.

The alternative taken here: a **userspace CH340 driver in pure Python** that speaks to the chip
through `ioctl` calls on `/dev/bus/usb` and exposes it as an ordinary **pty**. Klipper opens the
pty like any serial device and never knows the difference. No kernel rebuild, no extra
hardware soldered to the board's UART, no Octo4a.

Everything above the driver — Klipper, Moonraker, Mainsail, supervision, boot persistence — is
what this repository documents.

## Status

It works, and it was measured rather than assumed:

| What | Result |
|---|---|
| Idle, connected | 44 min, `state: ready`, reading bed, hotend and MCU temperatures |
| Pure motion stress | 4.7 min of diagonals at 150 mm/s, zigzag and 700 segments of 2 mm — `Timer too close: 0`, `print_stall: 0`, `bytes_invalid: 0` |
| A real print | 36.5 min, 9.73 m of filament, `complete` — `Timer too close: 0`, `print_stall: 0` |
| Pause / resume / cancel | Exercised on a sacrificial Benchy |
| Link quality | `srtt` 6–8 ms (the reference PC gives 3 ms), `rttvar` 1–2 ms |
| Recovery | Killing the bridge and doing nothing brings the printer back to `ready` in 48 s |
| Boot | The phone was rebooted; SSH and all five services came back on their own |
| Battery | ~6 %/h while printing; a hub with a power-delivery input charges the phone while it is USB host |

Numbers and method are in [`docs/en/results.md`](docs/en/results.md).

## The path, end to end

```
Ender 3 V3 SE mainboard (GD32F303, STM32F103-compatible)
   │  USART1, 250000 baud
   ▼
CH340  (1a86:7523)  ── USB ──►  rooted Android phone (USB host)
                                   │  /dev/bus/usb/BBB/DDD   (root)
                                   ▼
                            ch341_pty.py  — the driver, pure Python, USBDEVFS ioctls
                                   │
                                   ▼
                            pseudo-terminal (/dev/pts/N) + stable symlink ~/printer
                                   │
                                   ▼
                            klippy  ([mcu] serial: ~/printer)
                                   │  unix socket
                                   ▼
                            Moonraker (:7125)  ◄──  Mainsail (:8080, static files)
```

Five [runit](https://smarden.org/runit/) services keep it standing: `bridge`, `klippy`,
`moonraker`, `mainsail` and `watchdog`. The watchdog exists because a supervisor only restarts
processes that die, and a Klipper host that lost its pty does not die — it sits in `shutdown`.

## Where to start

| | |
|---|---|
| [`docs/en/pitfalls.md`](docs/en/pitfalls.md) | **Read this first.** Every silent failure met along the way, with the symptom each one produces. It is the reason this repository exists |
| [`docs/en/setup.md`](docs/en/setup.md) | The recipe, in the order that works |
| [`docs/en/architecture.md`](docs/en/architecture.md) | How the pieces fit, and why each one is there |
| [`docs/en/decisions.md`](docs/en/decisions.md) | Why a phone and not a Pi, why KernelSU and not Magisk, why a driver and not a kernel rebuild |
| [`docs/en/results.md`](docs/en/results.md) | The measurements |
| [`docs/en/prior-art.md`](docs/en/prior-art.md) | What already existed, and where each project stops |
| [`patches/`](patches/) | The two changes Klipper needs on Android, and the one Moonraker needs |
| [`services/`](services/) | The runit service definitions and the boot script |
| [`scripts/`](scripts/) | The watchdog, the static server for Mainsail, and a small API client |
| [`config/`](config/) | A minimal `moonraker.conf` and the `[mcu]` section for `printer.cfg` |

## Hardware this was done on

* **Printer:** Creality Ender 3 V3 SE, mainboard `CR4NS200320C13`, MCU **GD32F303RET6**
  (STM32F103-compatible), serial on USART1 through a CH340 at 250000 baud. The V3 SE ships with
  two possible boards (F103 and F401) and both use a CH340 — you cannot tell them apart from
  software. This one is the F103.
* **Phone:** Samsung Galaxy S9+ (SM-G9650, Snapdragon 845), Android 10, kernel 4.9 with
  **KernelSU-Next**. Its kernel has `usbserial`, `ftdi_sio`, `pl2303` and `cdc_acm`, but **no
  `ch341`** — which is the whole reason for the driver.
* **Hub:** a USB-C hub with a power-delivery input. Without one the phone, being USB host,
  *supplies* power and cannot charge.

Nothing here is specific to Samsung or to the S9+ beyond the debloat notes; what matters is
root, a Termux environment and a kernel without `ch341`.

## Requirements, in one paragraph

A rooted phone (root is needed only to open `/dev/bus/usb`), Termux installed from F-Droid or
GitHub (the Play Store build is abandoned), the printer **powered on** (the CH340 enumerates on
USB power alone but the MCU only answers with the printer's 24 V), and a Klipper host checkout
whose version **matches the firmware on the board** — a mismatch produces `MCU Protocol error`,
which looks exactly like a stale firmware and sends the diagnosis elsewhere.

## Licence

**GPL-3.0-only.** The patches are derivative works of Klipper and Moonraker, both GPL-3.0, so
the repository as a whole carries the same licence. The driver is published
separately under **GPL-2.0-only**, because its chip initialisation is translated from the Linux
kernel's `ch341.c` — the two licences are incompatible for combination, which is why the two
repositories are kept apart on purpose.
