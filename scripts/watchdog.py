#!/data/data/com.termux/files/usr/bin/python
"""Klippy watchdog: recovers the board when it drops into shutdown.

It exists because runit only restarts a process that DIES, and a klippy in
shutdown stays alive -- so ordinary supervision never reaches it. This is the
real case: when the bridge drops (the printer re-enumerates), runit brings the
bridge back with a NEW pty, but klippy keeps holding the descriptor of the old
one.

The sequence that works, measured, and in this order:
     1. sv restart klippy      -> picks up the new pty
     2. FIRMWARE_RESTART       -> takes the MCU out of shutdown
   Reversed it does nothing: FIRMWARE_RESTART before the klippy restart talks
   to a dead descriptor. No need to power-cycle the printer.
"""
import json, subprocess, time, urllib.request

MOONRAKER = "http://127.0.0.1:7125"
# Our OWN service directory, not the system's $PREFIX/var/service. When the
# stack moved here this path was left behind, and "sv restart klippy" started
# failing SILENTLY with "runsv not running" -- half of the recovery dead without
# anyone noticing, because the FIRMWARE_RESTART that follows masked it.
SV        = "/data/data/com.termux/files/home/pdata/sv/klippy"
INTERVAL  = 15      # s between polls
CONFIRM   = 2       # consecutive bad readings before acting (avoids acting on a normal restart)
BACKOFF   = 180     # s to wait after a recovery that FAILED (see the loop)

def state():
    try:
        with urllib.request.urlopen(MOONRAKER + "/printer/info", timeout=8) as r:
            return json.load(r).get("result", {}).get("state")
    except Exception:
        return None   # Moonraker down: not klippy's problem

def recover():
    print("recovering: sv restart klippy", flush=True)
    subprocess.run(["sv", "restart", SV], timeout=60)
    time.sleep(20)
    print("recovering: FIRMWARE_RESTART", flush=True)
    try:
        req = urllib.request.Request(MOONRAKER + "/printer/firmware_restart", method="POST")
        urllib.request.urlopen(req, timeout=45).read()
    except Exception as e:
        print("FIRMWARE_RESTART failed: %r" % e, flush=True)
    time.sleep(15)
    final = state()
    print("state after recovery: %s" % final, flush=True)
    return final

bad, last = 0, 0.0
print("watchdog up", flush=True)
while True:
    s = state()
    if s in ("shutdown", "error"):
        bad += 1
        if bad >= CONFIRM and time.time() - last > BACKOFF:
            print("klippy in %s for %d readings" % (s, bad), flush=True)
            # The backoff only applies when the recovery FAILS. If klippy came
            # back to "ready", the next drop is a NEW incident and deserves
            # action at once. Otherwise a second drop seconds after a successful
            # recovery sits in a 3-minute penalty box, needing a manual RESTART.
            # It does not become a loop because CONFIRM still holds the trigger
            # for ~30 s, and recover() takes ~35 s.
            last = 0.0 if recover() == "ready" else time.time()
            bad = 0
    else:
        bad = 0
    time.sleep(INTERVAL)
