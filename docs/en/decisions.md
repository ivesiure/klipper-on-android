# Decisions, and why

## Why a phone and not a Raspberry Pi

The argument is one of **allocation**, not taste. A Pi can be customised and put to many
uses; the phone still works well and had none. And the phone brings, from the factory, what a
Pi would need built around it: a battery, charging, a screen, and sensors readable from the
shell. There is evidence for that in the project's own history — hours were spent designing,
for the Pi, a UPS with a microcontroller, an optocoupler on the mains and a power-cycle
circuit. The phone ships with all of it.

## Why KernelSU and not Magisk

Seven attempts with Magisk failed, every one in a bootloop, and all for the same reason:
Magisk injects `magiskinit` into the **ramdisk**, and on this device that was the layer that
was broken. The usual suspects were eliminated with evidence — Magisk version (two very
different releases failed identically), reduced tar versus full firmware package (the
`boot.img` was byte-for-byte identical), `/data` encryption (formatted with the new boot
already flashed), bootloader rejection (the screen proves it accepts the image), AVB 2.0 (the
`vbmeta` partition is zeroed) and dm-verity (flags absent from the ramdisk, confirmed by
reading it).

KernelSU compiles root into the kernel itself, does not touch the ramdisk, and booted on the
first try.

The manager app version **must match the kernel's**. With a newer app it displays "running"
and still does not work, because that number is the kernel introducing itself, not the app.

## Why a driver of our own and not Octo4a

The whole ecosystem installs Octo4a — a complete OctoPrint server in Java — only to borrow its
serial driver. And with a CH340 that fails: there is an issue about exactly this, closed
without a solution, and it is the first search result for the symptom. See
[`prior-art.md`](prior-art.md).

## Why not rebuild the kernel with `ch341`

It is one line in the defconfig (`CONFIG_USB_SERIAL_CH341=y`) and the source is public. It
remains a valid exit — but it requires a toolchain, a build and flashing a boot image, and the
userspace driver solves it with none of that. If the userspace driver ever becomes a nuisance,
the kernel option is one line away.

## Why not an external CDC-ACM bridge (ESP32-C3, FTDI, RP2040)

It works too: the kernel **does** have `cdc_acm`, `ftdi_sio` and `pl2303`. It was the plan
until the driver worked. It needs a part and soldering onto the board's UART — opening the
printer. It stays as plan B.

## Why the trio also stays on the previous host

The previous Klipper host (a home server running the stack in containers) keeps its
`klipper`, `moonraker` and `mainsail` containers, **stopped**, as a backup. The way back is
starting them and moving the USB cable — with the phone unplugged from the board first, since
two hosts on one serial port is not a state anyone wants. The server's reverse proxy forwards
the old Mainsail address to the phone, so nothing in anyone's bookmarks changed.

## Why the patches were not sent upstream

Both bugs are real and remain unfixed upstream (`chelper` without `-lm`, `os.getloadavg()`
called bare in `statistics.py`). But the return was uncertain — Klipper reviews slowly, and the
`getloadavg` one would run into a legitimate "we do not support Android" — and the cost was
review time. The `.diff` files here are therefore a **rebuild recipe**, not pull-request
material: if Klipper or Moonraker are ever reinstalled on the phone, this is how two days of
diagnosis are not repeated.
