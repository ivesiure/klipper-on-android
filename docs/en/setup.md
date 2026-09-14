# Setup

Read [`pitfalls.md`](pitfalls.md) first. Almost every step below has a silent way of going
wrong, and the pitfalls document is where each one is explained.

Paths assume Termux's home, `/data/data/com.termux/files/home`, referred to as `~` below. The
stack keeps its state under `~/pdata` (`config/`, `logs/`, `run/`, `gcodes/`, `sv/`).

## 0. Prerequisites

* A **rooted** Android phone. Here: KernelSU-Next. Root is needed for one thing only — opening
  `/dev/bus/usb`.
* **Termux** from F-Droid or GitHub. The Play Store build is abandoned.
* The printer **powered on**. The CH340 enumerates on USB bus power alone, but the MCU only
  answers with the printer's own 24 V supply.
* A USB-C hub with a power-delivery input, if you intend to print anything long. As USB host
  the phone supplies power and does not charge without one.

## 1. Termux environment

```bash
pkg install -y python clang libffi git make openssh termux-services iproute2
```

For remote access: `passwd`, then `sshd` (it listens on port **8022**). Everything that follows
is far easier over SSH than on the phone's screen.

## 2. The bridge

Get [`ch341_pty.py`](https://github.com/ivesiure/ch341-userspace-pty) and run it as root:

```bash
su -c "HOME=$HOME LINK=$HOME/printer nohup /data/data/com.termux/files/usr/bin/python $HOME/ch341_pty.py > $HOME/bridge.log 2>&1 &"
```

The log should name the device, the chip version, the endpoints and the pty. `tx`/`rx`
counters growing with `errors=0` is the sign of health. Note the full path to `python` and the
explicit `HOME` — root's `PATH` does not include Termux, and root's home is `/`.

This is the hand-started form, for the first tests. Under supervision the same thing is done by
`services/bridge/run`, which also waits for the chip to appear before spending a process on it.

## 3. Klipper

The host version **must match the firmware on the board**, or you get `MCU Protocol error` —
which is identical to the error a stale firmware produces and sends you in the wrong direction.
Here the board runs a fork that drives the printer's original display, pinned to a specific
commit; use whatever your firmware was built from and set `.version` to match.

```bash
git clone <your klipper fork> klipper
git -C klipper checkout <commit the firmware was built from>
printf %s "<version string reported by the firmware>" > klipper/klippy/.version
```

Virtualenv and dependencies (see the greenlet pitfall):

```bash
python -m venv klippy-env
grep -v "^greenlet" klipper/scripts/klippy-requirements.txt > req.txt
./klippy-env/bin/pip install "greenlet>=3.2"
./klippy-env/bin/pip install -r req.txt
```

### The two mandatory patches — apply them, do not just read about them

```bash
git -C klipper apply /path/to/patches/klipper-android.diff
```

1. `-lm` in `COMPILE_ARGS` (`klippy/chelper/__init__.py`). On Bionic `libm` is not resolved
   implicitly; the C helper compiles but does not load.
2. A fallback for `os.getloadavg()` (`klippy/extras/statistics.py`), reading `/proc/loadavg`
   instead. The function does not exist on Android.

If your checkout has drifted from the one the diff was made against, `git apply` will fail and
the two hunks are small enough to apply by hand.

### Verify they went in, *before* starting

The two failures lie in different ways, and the second is the worse one:

```bash
grep -q -- '-lm' klipper/klippy/chelper/__init__.py     && echo "patch 1 ok" || echo "PATCH 1 MISSING"
grep -q 'proc/loadavg' klipper/klippy/extras/statistics.py && echo "patch 2 ok" || echo "PATCH 2 MISSING"
cd klipper/klippy && ../../klippy-env/bin/python -c "import chelper; chelper.get_ffi()" && echo "chelper loads"
```

Without patch 1, `chelper` fails to load — loudly, you see it immediately. Without patch 2,
`Loaded MCU` **is printed**, everything looks right, and `klippy` dies one second later from a
statistics timer. That is the failure that sends the diagnosis to the bridge, the serial link,
the firmware — anywhere but a stats module. Hence the check comes before starting, not after.

## 4. Configuration

In the `[mcu]` section of `printer.cfg`:

```ini
[mcu]
serial: /data/data/com.termux/files/home/printer
baud: 115200
restart_method: command
```

The `baud` is **fictional** — the real rate (250000) is set by the bridge on the chip. pyserial
refuses non-standard rates on a pty, and there is no UART on that side anyway.

`restart_method: command` is **mandatory**: the default reset toggles DTR, which a pty does not
have (see pitfalls).

If `printer.cfg` came from another host, grep it for absolute paths: a `[virtual_sdcard]`
pointing at a directory that does not exist here makes every upload "vanish" at print time
(see pitfalls).

## 5. Start `klippy`

```bash
nohup ./klippy-env/bin/python klipper/klippy/klippy.py \
  -I ~/pdata/run/klipper.tty \
  -a ~/pdata/run/klipper.sock \
  -l ~/pdata/logs/klippy.log \
  ~/pdata/config/printer.cfg &
```

All three paths are explicit because the defaults point at `/tmp`, which Termux does not have.

Under supervision `klippy` runs as **root** (`services/klippy/run`), for a reason that only
shows up after a reboot: the bridge's pty carries a SELinux label an app process cannot open,
and no amount of `chmod`, `chown` or `chcon` changes that. See the SELinux section of the
pitfalls. Hand-started with `nohup` from a root shell it works either way, which is exactly
what hides the problem.

## 6. Verify by effect, not by the absence of errors

```bash
awk '/Start printer at/{n=NR} /Loaded MCU/{m=NR} END{print (m>n)}' ~/pdata/logs/klippy.log   # 1 = board answered
grep -c "Unhandled exception" ~/pdata/logs/klippy.log                                        # 0 = stayed up
grep -o "srtt=[0-9.]* rttvar=[0-9.]*" ~/pdata/logs/klippy.log | tail -3
grep -o "bytes_retransmit=[0-9]* bytes_invalid=[0-9]*" ~/pdata/logs/klippy.log | tail -2
grep -c "Timer too close" ~/pdata/logs/klippy.log
```

And remember that the log going quiet after a minute is normal — an idle Klipper writes
nothing. The API socket is the source of truth (`scripts/klipctl.py`, or the one-liner in the
pitfalls).

## 7. Moonraker and Mainsail

This is what gives you pause, resume and cancel, and therefore what makes it reasonable to
print something you care about.

```bash
pkg install -y libsodium python-pillow libjpeg-turbo unzip
git clone --depth 1 https://github.com/Arksine/moonraker.git ~/moonraker

# --system-site-packages: reuse Termux's python-pillow instead of building Pillow on 3.14.
python -m venv --system-site-packages ~/moonraker-env
~/moonraker-env/bin/pip install -r ~/moonraker/scripts/moonraker-requirements.txt
```

Moonraker has its own mandatory patch (`patches/moonraker-android.diff`): `proc_stats` scans
`/sys/class/hwmon/`, which exists but an app process cannot open — `isdir()` passes,
`scandir()` raises, and the component takes Moonraker down on load. Under a supervisor that is
a restart loop.

```bash
git -C ~/moonraker apply /path/to/patches/moonraker-android.diff
grep -q '_hwmon_ok' ~/moonraker/moonraker/components/proc_stats.py && echo "patch ok" || echo "MISSING"
```

Every compiled dependency — `streaming-form-data`, `dbus-fast`, `zeroconf`, `libnacl` — built
a `cp314-android_24_arm64_v8a` wheel without intervention. Python 3.14 was not an obstacle
here.

Run it **as a module, from inside the repository**; `server.py` no longer works directly:

```bash
cd ~/moonraker && nohup ~/moonraker-env/bin/python -m moonraker -d ~/pdata &
```

A minimal `moonraker.conf` is in `config/`. The two fields that matter:

```ini
[server]
klippy_uds_address: /data/data/com.termux/files/home/pdata/run/klipper.sock
[machine]
provider: none
```

**Mainsail**, served without nginx (Termux's nginx does not link, and the obvious fix can take
`sshd` down with it — see pitfalls):

```bash
mkdir -p ~/mainsail && cd ~/mainsail
curl -sSL -O https://github.com/mainsail-crew/mainsail/releases/latest/download/mainsail.zip
unzip -oq mainsail.zip && rm mainsail.zip
# in config.json: "hostname": null, "port": 7125, "instancesDB": "browser"
nohup ~/moonraker-env/bin/python ~/serve_mainsail.py &   # Tornado, port 8080
```

`"hostname": null` makes Mainsail talk to Moonraker at the host of its own URL, so the setup
survives the phone changing IP address.

### Verify, again by effect

```bash
curl -s http://<phone>:7125/server/info | grep -o '"klippy_connected":[a-z]*'   # true
curl -s -o /dev/null -w '%{http_code}\n' http://<phone>:8080/                   # 200
curl -s "http://<phone>:7125/printer/objects/query?extruder"                    # live temperature
```

Then open Mainsail in a browser. `curl` does not apply CORS, so a `200` from it does not prove
the interface will connect — if the page stays on "Connecting", the origin you are using is
missing from `cors_domains`.

## 8. Supervision and boot

Once everything works by hand, put it under runit. `services/` holds the five definitions
(`bridge`, `klippy`, `moonraker`, `mainsail`, `watchdog`) and the boot script.

Use a **service directory of your own**, `~/pdata/sv`, not `$PREFIX/var/service`: that one
belongs to packages, and the services shipped there spin in a log-restart loop that burned 22
minutes of CPU in 14 hours. Copy the definitions without any `supervise/` directory.

```bash
mkdir -p ~/pdata/sv && cp -r services/{bridge,klippy,moonraker,mainsail,watchdog} ~/pdata/sv/
cp scripts/watchdog.py scripts/serve_mainsail.py ~/
runsvdir ~/pdata/sv &
```

Boot persistence needs the **Termux:Boot** add-on, signed with the same key as your Termux
(`dumpsys package com.termux` tells you which build you have), plus the two `su` steps in the
pitfalls — arming the receiver and exempting both packages from Doze. The boot script goes in
`~/.termux/boot/`. Its first line starts `sshd`, on purpose: whatever else fails, you can still
get in.

**Then reboot the phone.** It is the only thing that proves persistence, and it is where the
SELinux wall shows up if any service is still running as the wrong user.

The recovery path was measured rather than assumed: kill the bridge, touch nothing, and the
printer is back to `ready` in 48 seconds.

## 9. Debloat (optional, but it pays)

The phone becomes a headless printer host; nearly every stock app is dead weight. Choose what
to remove by what **runs** (`dumpsys meminfo`) and by what **wakes the device**
(`dumpsys batterystats`), not by what is installed — and keep a keyboard, the launcher,
settings and everything Wi-Fi. With no SIM inserted, airplane mode with Wi-Fi on removes the
single largest consumer, the modem searching for a network. Details and the one trap this
sprang (a telephony crash loop on the next reboot) are in the pitfalls.
