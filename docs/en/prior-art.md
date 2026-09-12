# Prior art

Surveyed in September 2026. The state of the art moves; re-check before citing as current.

## Verdict

Partial prior art is abundant; nothing equivalent was found. Nobody had published the
combination: a CH341 driver **in pure Python, through USBDEVFS ioctls, with no libusb or
pyusb**, bridged to a **pty**, on rooted Android, validated against Klipper's handshake.

## The finding that matters most: this case is a known, open problem

Every Klipper-on-Android project solves the serial port the same way — installing Octo4a in
full just to borrow its driver, and pointing `[mcu]` at `/var/octo4a/serialpipe`. With a CH340
that fails:

* `d4rk50ul1/klipper-on-android` issue #24 — *"klipper is failing to connect to CH340 with
  driver from Octo4a"*, `Timeout on connect` in `identify_response`. Closed without a solution.
  It now carries a comment with the alternative path and the two findings that hold
  independently of the driver: the pty in raw mode on both ends, and the fictional
  `baud: 115200`.
* `feelfreelinux/octo4a` issue #347 — attributes part of it to DTR toggling on baud-rate
  change.
* Klipper forum: *"CH340 - 250000 baud rate not supported"*.

The `identify` handshake was completed here at 250000 baud with a CH340.

## Klipper with an Android host

| Project | Where it stops |
|---|---|
| `d4rk50ul1/klipper-on-android` | README says to install Octo4a for the CH34x driver |
| `galangtirta9/DroidicKlipper` | Root via Magisk; serial through Octo4a's `serialpipe` |
| `RyanEwen` (gist, Linux Deploy) | Same Octo4a dependency |
| `umeiko/KlipperPhonesLinux` | The opposite road: replaces Android with Ubuntu/postmarketOS and rebuilds the kernel |
| `feelfreelinux/octo4a` | The closest: its `VirtualSerialDriver.kt` **does create a pty**. But it is Kotlin over the Android USB Host API, inside an app with a UI |

## Userspace serial-to-pty bridges

| Project | Where it stops |
|---|---|
| `MarkWllms/Termux-serial-tty` | Technically the closest — creates a pty. But C++ with libusb, and depends on `termux-usb` |
| `thingsapart/usbuart-termux` | Has a Klipper section in its README. Baud fixed at 115200, and the author states it was never built or tested |
| `jacklinquan/usbserial4a` | Python, but through pyjnius over the Java API, and does not create a pty |
| `gio3k/usbselfserial` | C++ header-only, libusb, iOS-focused, "not production ready" |
| `anszom/vtty` | A kernel module |

## CH341 in Python over USBDEVFS

Nothing. The Python CH341 projects are all I2C/SPI/GPIO (`karlp/ch341-py2c`,
`pine64/libch341-spi-userspace`), over libusb. The vendor's driver
(`WCHSoftGroup/ch341ser_linux`) is a kernel module.

## What is different here, in five points

1. Pure Python, standard library only — the equivalents are C/C++ with libusb, or Java/Kotlin.
2. Root straight to `/dev/bus/usb`, without `termux-usb` and without an intermediary app.
3. No Octo4a.
4. The correct rate at 250000 baud, which is where the others break.
5. Evidence that it works — the handshake the open issues never closed, and real prints after
   it.
