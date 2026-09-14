# Pitfalls

This is the most valuable document in the repository. Every entry describes a failure that is
either **silent** or **points the diagnosis somewhere else** — which is what made each one
expensive. They are grouped by layer and, within each group, roughly by how much they cost.

Whenever a fix is given, it is the one that actually held, not the first one tried.

## Protocol and serial

### Klipper's VLQ threshold is `0x60`, not `0x80`

Klipper encodes integers as variable-length quantities. The natural assumption is that a value
fits in one byte when it is below `0x80`. It does not: the parser uses `(c & 0x60) == 0x60` as
the **sign** marker, so values from 96 to 127 need two bytes, and a single-byte encoding of
them is read by the MCU as a negative number.

```python
if v >= 0x60 or v < -0x20:
    out.append(((v >> 7) & 0x7f) | 0x80)
out.append(v & 0x7f)
```

The symptom is exact and misleading: requesting the data dictionary in 40-byte chunks works
up to offset 80 and then **stalls at 120 bytes received, always at the same point** — which
looks like a transport failure.

### The pty needs raw mode on both ends

A pseudo-terminal comes with a line discipline, and the line discipline eats protocol bytes.
The fatal case: `0x11` and `0x13` are XON/XOFF, and Klipper's sequence byte is `0x10 | n` —
so `0x11` shows up constantly.

The symptom is a transfer that returns **zero bytes, with no error anywhere**. Both the driver's
side of the pty and the reader's side must be put in raw mode.

### A block split across reads must not be discarded

Through a pty the data arrives fragmented. A framer that advances by one byte when the block is
incomplete eats the beginning of that block.

```python
if n < 5 or n > 64:      # garbage: drop only this byte
    i += 1; continue
if i + n > len(buf):     # incomplete: keep it for the next read
    break
```

### `0x7e` does not delimit blocks reliably

The sync byte appears inside compressed payloads (the data dictionary comes zlib-compressed).
Frame by the length byte and validate the CRC16-CCITT instead of scanning for `0x7e`.

### Repeating a sequence number floods you with empty acks

The MCU treats a block with a repeated `seq` as a retransmission and answers with an empty ack
(`05 11 8f 08 7e`). Over 6 KB of those went by before the cause was found. The `seq` carried by
a received block is the one the MCU expects **next** — use that.

## Klipper on Android

### `chelper` compiles but does not load: `-lm` is missing

```
dlopen failed: cannot locate symbol "atan2"
```

The shared object **is** produced; it only fails at `dlopen`, which makes it look like a
toolchain problem. glibc resolves `atan2` implicitly; **Bionic does not**. Add `-lm` to
`COMPILE_ARGS` in `klippy/chelper/__init__.py` — see `patches/klipper-android.diff`.

### `os.getloadavg()` does not exist on Android — and it kills `klippy` *after* it connects

```
AttributeError: module 'os' has no attribute 'getloadavg'
```

It is called from `klippy/extras/statistics.py`. This is the worst of the two patches to miss:
`Loaded MCU` is printed, everything looks right, and the process dies a second later from a
**statistics timer**. You will look at the bridge, the serial link and the firmware before you
look at a stats module. The fix that keeps the feature is to fall back to `/proc/loadavg`,
which does exist on Android. Verify the patch is applied **before** starting `klippy`
(`docs/en/setup.md` has the one-liners).

### The pty's baud rate is fictional — and that solves an error that looks fatal

```
NotImplementedError: non-standard baudrates are not supported on this platform
```

pyserial tries to configure 250000 baud on the pty, and 250000 is not a standard POSIX rate.
Do not fight pyserial: there is no UART on that side of the pseudo-terminal. The real rate is
set by the driver, on the CH340. Put `baud: 115200` in `[mcu]` and move on — nothing changes on
the wire.

### The pty has no DTR either — `restart_method: command` is mandatory

Klipper's default way of resetting a serial MCU (`_restart_arduino`) opens the port and toggles
DTR. A pty has no modem lines: `TIOCMBIS` fails with `ENOTTY` (measured with pyserial 3.4 and
3.5 — `ser.dtr = True` raises `OSError(25, 'Inappropriate ioctl for device')`). The exception
escapes `klippy`'s post-run handler, the MCU is never reset, and the next start finds it still
configured:

```
Failed automated reset of MCU 'mcu'
```

That message does **not** mean the board is stuck — it means it is alive, configured and
*not* in shutdown, when the host expected a fresh one. Power-cycling it will not help.

The fix is one line in `[mcu]`:

```ini
restart_method: command
```

The reset now travels over the link like any other message (`Attempting MCU 'mcu' reset
command` in the log). Note the consequence: if the host's send queue is wedged — as it was in
the 2026-09-14 incident, when a bug in the display module's `TJC3224.py` (class-level
`data_frame` list, growing 5 bytes per FIRMWARE_RESTART in the same process) queued a message
too large for a Klipper block and `serialqueue` spent the link on empty 5-byte blocks — the
`reset` sits behind the wedged message and you get the same "Failed automated reset". The
difference is in `Stats`: `send_seq` climbing ~2 000/s with ~5 bytes per message, and
`ready_bytes` creeping up by one per second (the `get_clock` queries that never leave). The
bridge's `tx` counter matches `bytes_write` exactly; it is a faithful witness, not the cause.

### `klippy`'s `-I` defaults to `/tmp/printer`, and `/tmp` does not exist in Termux

Termux's temporary directory is `$PREFIX/tmp`. Pass `-I`, `-a` and `-l` explicitly.

### The log going quiet does not mean `klippy` died

`klippy.log` froze at a `Stats` line and wrote nothing for 43 minutes. The process was still in
`ps`, and the naive reading — "it hung" — was wrong: the API socket answered
`{"state": "ready", "state_message": "Printer is ready"}` the whole time.

The cause is in `statistics.py`:

```python
if max([s[0] for s in stats]):
    logging.info("Stats %.1f: %s", eventtime, stats_str)
```

Each callback returns `(active, text)`. With the printer idle no subsystem declares itself
active, and Klipper writes nothing. **Silence in the log means idle, not dead.**

Two wrong readings this invites, both made here:

* `Stats N` is not the host's uptime. `N` is the machine's monotonic clock. Real uptime comes
  from the `Start printer at ... (<epoch> <monotonic>)` line: subtract the starting monotonic
  value from the last `Stats`.
* `ps` showing the process does not prove it is connected, and `State: S (sleeping)` is the
  normal state of an event loop, not a hang.

The check that is worth something, and is read-only (it does not move the machine):

```bash
python -c '
import socket, json
s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM); s.settimeout(6)
s.connect("/data/data/com.termux/files/home/pdata/run/klipper.sock")
s.sendall(json.dumps({"id": 1, "method": "info", "params": {}}).encode() + b"\x03")
print(s.recv(4096).split(b"\x03")[0].decode())'
```

Verify by effect, not by the absence of errors.

### MCU stuck in shutdown — and the order that actually recovers it

If `klippy` goes down, the board stays in shutdown and reconnection fails with
*"Can not update MCU config as it is shutdown"*. This is not a bridge fault — the link is
perfect while the board refuses configuration.

It recovers without touching the printer, **provided the order is this one**:

```
1. sv restart klippy      # picks up the new pty
2. FIRMWARE_RESTART       # takes the MCU out of shutdown
```

Reversed, it does nothing. `FIRMWARE_RESTART` alone returns `{"result": "ok"}` and changes
nothing, because `klippy` is still talking to the **old pty's file descriptor** — the pty dies
with the bridge, and the restarted bridge creates a new one (`/dev/pts/1` becomes
`/dev/pts/3`). No command that travels over the link can repair a link that no longer exists.
`scripts/watchdog.py` automates exactly this sequence.

## Configuration inherited from elsewhere

### `printer.cfg` carries paths from another host — and uploads "vanish"

When the print is started from Mainsail:

```
virtual_sdcard file open
KeyError: 'speedteststructure_pla_36m32s.gcode'
Unable to open file
```

The file uploaded correctly. Moonraker stored it in its `gcodes` directory and
`/server/files/list` shows it. The one that cannot find it is `klippy`, because the
`[virtual_sdcard]` section of a `printer.cfg` copied from a previous host (here, a container)
pointed at a directory that does not exist on the phone.

The symptom misleads twice: the `KeyError` shows the name in lower case because Klipper matches
names case-insensitively, which makes it look like a filename problem; and the interface shows
the file, because Moonraker does the listing, not `klippy`. **The two look at different
directories, and only `klippy` is wrong.** Grep `printer.cfg` for any absolute path that did
not come from this machine.

## Moonraker and Mainsail on Android

### `[machine] provider: none` — without it Moonraker does not start

Moonraker's default is to talk to systemd over D-Bus, and Android has neither. `provider: none`
under `[machine]` is mandatory. The known cost: `update_manager` and service control from the
interface (restart/stop) stop working.

### The `ip` command does not exist in Termux — and Moonraker calls it

```
FileNotFoundError: [Errno 2] No such file or directory: 'ip'
ShellCommandError: Error running shell command: 'ip -json -det address'
```

Not fatal — Moonraker starts and works — but it fills the log on every network update.
`pkg install iproute2`.

### Termux's nginx does not link — and the obvious fix is dangerous

```
CANNOT LINK EXECUTABLE "nginx": cannot locate symbol "SSL_set_quic_tls_cbs"
```

The nginx package was built against a newer OpenSSL than the one installed. **Do not solve
this with `pkg upgrade openssl`:** `openssh` links against the same library, and if `sshd`
breaks you lose the only remote access to the device — the rest is fixed by hand, at the
phone.

The route that avoids the problem entirely: Mainsail can talk to Moonraker directly, without a
proxy. In its `config.json` set `"hostname": null` and `"port": 7125`. The `null` makes
Mainsail use the host of its own URL, so this also survives the phone changing IP address. The
static files are served by a 12-line Tornado script (`scripts/serve_mainsail.py`) — Tornado is
already in Moonraker's virtualenv.

If you ever go back to a proxy: the Mainsail bundle does not proxy by itself. Without routing
`/websocket`, `/printer`, `/api`, `/access`, `/machine` and `/server`, the interface loads and
stays on "connecting" forever — a symptom that says nothing about the cause.

### Moonraker became a package: `server.py` no longer runs directly

```
ImportError: attempted relative import with no known parent package
```

Run `python -m moonraker -d <data-dir>` **from inside the repository directory**.

### CORS: `curl` approves what the browser rejects

Moonraker returns **200 without `Access-Control-Allow-Origin`** for an origin outside
`cors_domains`. To `curl` that is success; to a browser it is a network failure, and Mainsail
shows an endless "Connecting" without naming CORS. When the consumer is a page, test with an
`Origin:` header — otherwise the test measures something else.

Two lists that get confused: `trusted_clients` authorises the **client** (by IP);
`cors_domains` authorises the **page** (by origin). The API answering does not prove the
interface will connect. And `http://*.local` does not match `http://localhost:8080` — that
wildcard is the `.local` domain, not the name `localhost` — nor does it match a host with a
port appended. Opening Mainsail in the phone's own browser needs `http://localhost:8080`
listed explicitly.

## SELinux: the wall that only appears after a reboot

Everything in this section worked when the processes were started by hand with `nohup`, and
broke on the first real boot. That is the reason not to trust "it works" before the machine
has been rebooted once.

The phone runs SELinux in **Enforcing**. The bridge, needing `/dev/bus/usb`, runs in the
KernelSU domain, `u:r:ksu:s0`. `klippy`, as an app process, is
`u:r:untrusted_app_27:s0:c...`. Three walls follow, and none of them is a file permission.

### The pty inherits the label of whoever created it — and the app cannot open root's

| Created by | Label |
|---|---|
| App | `u:object_r:untrusted_app_all_devpts:s0:c...` |
| Bridge (`ksu`) | `u:object_r:devpts:s0` |

`klippy` fails with `Permission denied` **even with the node at `crw-rw-rw-`**. `chown` does not
help, `chmod` does not help, and `chcon` is refused **even for root** — the policy does not
allow relabelling devpts to the app's type. Root does not beat SELinux in enforcing mode.

### The unix socket is checked against the server's context, not the file's label

```
Cannot connect to Klippy, Linux user 'u0_aNNN' lacks permission to open
Unix Domain Socket: .../klipper.sock
```

With the socket at `srwxrwxrwx`. Here `chcon` even succeeds (the type stays `app_data_file`;
only the MCS categories were missing) — **and it still does not work**, because `connectto` is
evaluated against the context of the **process serving** the socket, not the label of the
socket file.

### The conclusion: whoever talks to `klippy` must be in the same context

There is no middle ground. Since the bridge is forced to be `ksu`, **`klippy` and Moonraker
also run as root**. Mainsail's static server and the watchdog stay as the normal user: one only
serves files, the other talks to Moonraker over **TCP** (`127.0.0.1:7125`), and TCP is not
subject to this restriction.

`umask 0` on `klippy` is mandatory. Connecting to a unix socket requires **write** permission;
created by root with the default umask the socket comes out `0755` and blocks Moonraker by
plain DAC, before SELinux even gets a say.

A good side effect: files root creates inside the Termux home inherit `app_data_file`, so logs
and configs remain readable by the normal user.

## Supervision (runit)

### `runsv` cannot stop a process started through `su`

`sv down` and `sv restart` **hang until the timeout**: the `TERM` goes to `su`, which does not
forward it to the root process. This breaks the watchdog, which depends on `sv restart klippy`.

Fix, in the `run` files of `bridge`, `klippy` and `moonraker`: record the real pid and forward
the signal by hand. `exec` makes the shell become the process, so `$$` is already the final pid:

```sh
su -c "echo \$\$ > $PIDF; exec ..." &
child=$!
trap "p=\$(cat $PIDF); [ -n \"\$p\" ] && su -c \"kill \$p\"; exit 0" TERM INT
wait $child
```

### Moonraker restart-loops on `/sys/class/hwmon/`

```
PermissionError: [Errno 13] Permission denied: '/sys/class/hwmon/'
```

`proc_stats` does `os.path.isdir()` (which passes) and then `os.scandir()` (which raises), and
the component takes the whole of Moonraker down on load — under a supervisor that becomes a
restart loop. `patches/moonraker-android.diff` checks `os.access` first and falls back to
`/sys/class/thermal`, which is readable.

### `runsv` hands you an empty environment — and root's `~` on Android is `/`

The bridge went into a restart loop with:

```
OSError: [Errno 30] Read-only file system: '/dev/pts/1' -> '/printer'
```

The driver expands `~/printer`. Under `nohup` that worked because it inherited `HOME` from the
interactive shell. Under `runsv` there is **no `HOME` at all**, so `expanduser` falls back to
the user's `pwd` entry — and root's, on Android, is `/`. The target became `/printer`, on a
read-only filesystem.

Export `HOME` and `LINK` explicitly in the service's `run`. This holds for every service, not
just the bridge: never rely on the environment under a supervisor.

### The services that come with `termux-services` spin in a loop — and they are not yours

The most expensive busy loop in this stack. Measured 14 hours after a boot:

```
runsv sshd        50,338 ticks   (503 s of CPU)
runsv ssh-agent   50,322 ticks
runsv nginx       32,300 ticks
                  ────────────
runsv moonraker      178 ticks
runsv bridge         154 ticks
runsv klippy          28 ticks
runsv watchdog         2 ticks
runsv mainsail         2 ticks
```

**Twenty-two minutes of CPU burned by three services that were `down` and unused**, against
3.6 seconds for the entire stack built here.

The cause: their `log/run` points at `/sv/<name>`, a path that does not exist in this
installation. `runsv` starts the log service **even when the main service is `down`** — the
`svlogd` dies immediately, `runsv` resurrects it, forever.

Deleting the directories only lasts until the next `pkg upgrade`: they belong to packages
(`sshd/` and `ssh-agent/` to `openssh`, which is your access and cannot go; `nginx/` to
`nginx`).

The durable fix: **a service directory of your own.** Keep only your five services under
`~/pdata/sv` and point `runsvdir` there from the boot script. The package manager can recreate
whatever it likes in `$PREFIX/var/service`; none of it will be supervised.

When copying service definitions, do not bring `supervise/` along. `cp -a` copies the previous
supervisor's state (pids, fifos) and `runsv` will not start with the inherited lock — the
symptom is `runsvdir` alive, zero `runsv` processes, the whole stack down. `rm -rf */supervise`
before starting.

### runit only restarts what dies — and a `klippy` in shutdown does not die

The most expensive lesson of the supervision stage. When the bridge drops (which is what
happens whenever the printer re-enumerates), runit brings it back with a **new pty**. But
`klippy` **stays alive**, holding the old pty's descriptor, and goes into `shutdown`. To the
supervisor everything is fine: the process is up.

That is why `scripts/watchdog.py` exists — a fifth service that polls the printer state through
Moonraker and triggers the recovery sequence above. Measured end to end: kill the bridge, do
nothing, and the printer is back to `ready` in 48 seconds.

### Cutting power to the hub kills the print in progress

The phone's charger was swapped in the middle of a print. The charger feeds the **hub**, and
the phone talks to the printer **through it**. The hub went down and took the CH340 with it:

```
device gone: [Errno 19] No such device
watchdog: klippy in shutdown for 2 readings -> sv restart klippy -> FIRMWARE_RESTART -> startup
```

The watchdog did its job and recovered `klippy`. The print did not come back, and could not:
Klipper has no power-loss recovery. With the MCU in shutdown mid-job, the head position and
the move queue are gone. That is how Klipper works, not a defect of this stack.

The consequence: **the hub is a single point of failure for the print.** With the phone
plugged straight into the printer, fiddling with a charger affected nothing. Now it does — and
swapping a charger is exactly the kind of thing one does without thinking.

### `time.sleep` in a loop that waits for an event delays the process's death

Found in the same incident, and it was a regression introduced the same day. The bridge's main
loop was:

```python
while not stop.is_set():
    time.sleep(STATS_SECS)      # raised from 5 to 60 that day
```

The thread that detects the device vanishing calls `stop.set()`, but the main loop is asleep
and only checks when it wakes. At 5 seconds the delay went unnoticed; at 60, the bridge took
**up to a minute to die** — and the supervisor only restarts it after that. Precisely when you
want the process back quickly.

```python
while not stop.wait(STATS_SECS):   # returns immediately when the event is set
```

Measured: `Event.wait` returned in 0.10 s where `time.sleep` took the full interval.

And the "device gone" `print` had no `flush`. Since stdout is a pipe to `svlogd`, it is
block-buffered: the message only appeared in the log at the next flush. **The log recorded the
failure later than it happened** — which misleads exactly the person reconstructing an
incident from timestamps.

### A supervisor without a wait becomes a busy loop when the device is absent

Found by real use, not by testing: the printer was switched off and the bridge went into a
loop. The driver does not find the CH340, exits, and `runsv` — doing its job — resurrects it
about once a second. Measured: **122 attempts in 2 min 25 s**, each one spawning a `su`, a
Python interpreter and a sysfs scan. A night with the printer off would be ~24,000 restarts
and tens of MB of log, burning battery to discover the same thing 24,000 times.

The fix: wait for the device in `run`, before spending a process on it. A shell loop with
`sleep 5` costs one `grep` every five seconds:

```sh
has_ch340() { su -c "grep -qs 1a86 /sys/bus/usb/devices/*/idVendor" 2>/dev/null; }
while ! has_ch340; do sleep 5; done
```

After: 0 attempts in 45 s, against ~38 before.

The same applied to `klippy` on a smaller scale: it gave up on the pty after 60 s and
restarted, ~60 times an hour for nothing — the pty only appears when the bridge is up, and the
bridge only comes up when the printer is on. Now it waits indefinitely too.

The general lesson: a supervisor restarts what dies, and that is what you ask of it. If the
cause of death is an external condition that will take a while, the **service** is the one
that has to wait — otherwise correct supervision becomes correct waste.

### A service path embedded in a script breaks silently

When the stack moved to `~/pdata/sv`, the path hard-coded in the watchdog was left behind. Its
`sv restart klippy` started failing with `runsv not running` — and the watchdog did not check
the return code, so it went on to `FIRMWARE_RESTART` as if it had worked.

The defect stayed invisible because the second half masked the first: `FIRMWARE_RESTART` alone
sometimes recovers, when `klippy` already picked up a new pty for another reason. The recovery
"worked" in some cases and would have been dead in exactly the case it exists for — the bridge
dropping while `klippy` holds the old descriptor. Found by accident, testing something else.
When moving a service directory, search for the path **everywhere**: `run` files, boot scripts,
and inside the code of anything that calls `sv`.

### Without `termux-wake-lock` Android suspends everything

It goes in the boot script, before `runsvdir`.

### `sshd` does not start by itself — and a reboot would have left the device unreachable

The most dangerous trap of this stage, found **before** any reboot. `sshd` had been started by
hand: it is not under runit (the `sshd/` service ships with a `down` file) and had no boot
mechanism at all. The boot script only started `runsvdir`.

A reboot would have left the phone without SSH and without remote repair — only by hand, at
the device. `sshd` is now the **first line** of the boot script, before even the wake-lock, so
that a fault anywhere else in the stack still leaves a way in. When building an automatic
boot, start with the access path, not with the service you care about.

### Termux:Boot is an APK — and the signature has to match

`runsvdir` brings up the stack, but what starts it after a reboot is the **Termux:Boot** add-on,
a separate application. It can be installed over SSH with root (`pm install`), but the add-on
must be signed with the **same key** as the installed Termux.

Find out which: `dumpsys package com.termux`. `pkgFlags=[ DEBUGGABLE ]` with `installer=null`
means the **GitHub debug build**, so the add-on must be `termux-boot-app_*+github.debug.apk`;
the F-Droid one would be rejected for a signature mismatch. Confirm afterwards that
`signatures:[...]` is identical for both packages.

Installing is not enough. Two more steps, both through `su`:

```
am start -n com.termux.boot/.BootActivity            # arms the receiver; without it, it never fires
dumpsys deviceidle whitelist +com.termux.boot        # on Android 10, Doze swallows the receiver
dumpsys deviceidle whitelist +com.termux
```

### `pgrep -f` also matches its own command line

`pgrep -c -f klippy` counts your own SSH session. The bracket trick — `pgrep -f "[k]lippy"` —
does not match itself. The same applies, with worse consequences, to `pkill -f` (below).

## Environment

### The USB device number changes on every replug

`001/004`, then `001/005`, then `001/002` within a single session. Discover the device by
**VID:PID** by scanning `/sys/bus/usb/devices/*/idVendor`. Hard-coding the path is a guarantee
of breakage.

### `greenlet==3.1.1` does not build on Python 3.14 (Termux's)

Use `greenlet>=3.2`. And `pip` is atomic per invocation: with greenlet failing, **nothing** is
installed, although the wheels stay cached. Install with the greenlet line filtered out of the
requirements file. Every other old pin builds fine, including `markupsafe==1.1.1`.

### Python as root in Termux needs the full path

`su -c "/data/data/com.termux/files/usr/bin/python <script>"` — root's `PATH` does not include
Termux's binaries. And after `su`, `pkg` and `apt` disappear: manage packages as the normal
user.

### `pkill -f <pattern>` in a remote command kills your own session

If the pattern appears in the command line that invokes it, `pkill` matches that too. Several
SSH sessions were lost this way, with a symptom of "unstable network". Use a pidfile.

### Without a hub with a power-delivery input, the phone does not charge

It is USB host and **supplies** power. For anything long the hub is a requirement, not a
convenience — see the results for the numbers.

### `proot-distro` intercepts syscalls through ptrace

That adds latency in precisely the quantity this project cares about. Install natively in
Termux.

## Housekeeping on a Samsung host

These are specific to the phone used here, but the shape of the problem is general: a phone
turned into a headless server keeps running things a server has no use for.

### Choose what to remove by what *runs*, not by what is installed

A dormant APK costs nothing but disk. What costs battery is what executes:

```bash
dumpsys meminfo | sed -n '/Total PSS by process/,/Total PSS by OOM/p'
```

That is how the first list came out: the assistant, face service, app store, vendor account
services and the search app added up to ~470 MB running on a device whose job is a USB bridge.
`pm uninstall --user 0 <package>` removes for the user without deleting the APK (it stays in
`/system`, read-only), which is why `cmd package install-existing <package>` reverts it
without downloading anything — and why a factory reset brings everything back.

### Filtering by memory finds one thing; filtering by wake-ups finds another

The first pass used `dumpsys meminfo` and caught the heavy processes. Correct but incomplete —
on a device that is always awake, what costs battery is not occupying RAM, it is waking the
CPU. `dumpsys batterystats` shows what `meminfo` does not: scheduled jobs, push services and
temporary whitelists that wake the device on their own. And the radios, which are no package at
all: with no SIM inserted, `Cell standby` was the single largest consumer — the modem searching
for a network that will never come. **Airplane mode with Wi-Fi on** eliminates it, and Wi-Fi
survives airplane mode (confirmed by an uninterrupted SSH session). Bluetooth scanning and NFC
were also on and show up nowhere but in the battery history.

### Keep a keyboard, keep the launcher, keep settings

Without a real keyboard app you cannot type on the screen — and if Wi-Fi drops and you need to
re-enter a password at the device, you have no way to write it. With SSH as the only access,
the keyboard is insurance against lock-out. Never remove Termux, Termux:Boot, the system UI,
the launcher, settings, the package installer, or anything Wi-Fi related.

### Removing the vendor's OTA agent is a decision, not neglect

On a rooted device with a custom kernel, an over-the-air update arriving on its own can change
the kernel, the SELinux policy or permissions — in the middle of a print. The update agents
were removed deliberately.

### The first reboot after debloating put telephony in a crash loop

Symptom: the device "stuttering" every few seconds right after a reboot, with nothing new
open. Load average near 10; `system_server`, `logd` and `rild` at the top.

Cause: the vendor's IMS (VoLTE) service had been uninstalled for user 0, but the system still
registers its content provider as belonging to it. The phone process tries to bind it at boot,
fails with `SecurityException: Failed to find provider`, crashes, is restarted by Android, and
the vendor generates a **bug report (`dumpstate`) on every crash** — 124 crashes and 7 reports
in 20 minutes. It is the `dumpstate` that stutters. It did not show on the day of the
debloat because the phone process was already running and never re-bound the IMS; the next
reboot was the first since. Airplane mode does not prevent it: the attempt happens at boot,
before the radio matters.

Diagnosis in one command — one process, hundreds of times, is a loop:

```bash
su -c "logcat -d -b crash" | grep Process: | awk '{print $(NF-2)}' | sort | uniq -c
```

Fix: `su -c "pm install-existing <ims-package>"` — gives the system app back to the user (the
APK never left `/system/priv-app`). Crashes stopped at once; reversible with
`pm uninstall -k --user 0`.

### Removing a lock screen whose pattern was recorded wrong, with root

A pattern that was set and is not accepted (the fingerprint unlocks, but the device asks for
the pattern periodically). `cmd lock_settings clear --old …` does not help: it verifies the old
credential first, and without it there is nothing to verify. What worked, on a device whose
storage was **not encrypted** (`ro.crypto.state = unsupported` — without that this would be
dangerous): back up and remove `/data/system/locksettings.db*` and `/data/system_de/0/spblob/`,
then reboot. It comes up without a lock; fingerprints must be re-enrolled; user-installed CA
certificates are unaffected.
