# Results

Everything here was **measured**, not estimated. Where there is doubt, it is said.

## Reference: a PC host that has printed well for months

```
srtt=0.003   rttvar=0.000   rto=0.025
bytes_retransmit=9   in 14 MB of klippy.log
Timer too close: 0   (never)
```

The reference is 3 ms, not the 1–2 ms one tends to assume. That changes how everything below
reads.

## The phone, through the bridge

### Raw round-trip on the protocol (500 samples, synchronous Python loop)

```
min 4.57   median 5.39   mean 7.07   p95 11.44   p99 12.31   max 13.93   sd 2.60 ms
0 losses in 500
```

This is a **ceiling**, not `srtt`: it carries interpreter overhead and a loop that waits block
by block.

### As measured by Klipper itself, 150 s connected

```
srtt=0.006   rttvar=0.001   rto=0.025   min_half_rtt=0.001819
bytes_invalid=0        Timer too close: 0        print_stall=0
mcu_awake=0.006  mcu_task_avg=0.000018  mcu_task_stddev=0.000028
freq=71999773  (nominal 72000000)
bridge: tx=3758  rx=30067  errors=0
```

Reading the real machine: bed 19.0 °C, hotend 20.0 °C, MCU 23.6 °C.

### Long idle

Bridge and `klippy` started, and 44 minutes later the API socket still answered
`{"state": "ready", "state_message": "Printer is ready"}` — no exception.

```
srtt=0.007   rttvar=0.002   rto=0.025
bytes_invalid=0   bytes_retransmit=16   send_seq=285=receive_seq
freq=72000829  (nominal 72000000)
```

The log went silent after 62 s and that is not a fault — see the pitfall *"The log going quiet
does not mean klippy died"*.

## Under load: the test that decides

`Timer too close` only appears with step generation under load, so idle numbers prove the link
but not the host. The sequence, cheapest first:

### Pure motion — cold, no filament, Z parked at 10 mm

About 4.7 minutes: diagonals at 150 mm/s, zigzag, and 700 segments of 2 mm to stress the
step-compression path.

```
Timer too close: 0     print_stall: 0     bytes_invalid: 0
```

Use a full `G28`, not `G28 X Y`: the `z_hop` of `safe_z_home` only lifts the nozzle when Z is
homed, and after a boot the Z position is unknown.

### A real print

`SpeedTestStructure`, **36.5 min**, 9.73 m of filament, state `complete`.

```
Timer too close: 0     print_stall: 0
```

The first attempt failed for an unrelated reason — a `[virtual_sdcard]` path inherited from
the previous host (see pitfalls). The second went through.

### Pause, resume, cancel

Exercised on a sacrificial Benchy: pause keeping the heaters, resume continuing where it
stopped, cancel turning everything off.

### Recovery

Kill the bridge — which is what happens whenever the printer re-enumerates — and touch nothing:
the printer is back to `ready` in **48 s**. The watchdog's `sv restart klippy` plus
`FIRMWARE_RESTART` measured ~36 s on its own, three times.

## Battery

### How to measure it properly (and why the first attempt did not count)

The first measurement was invalidated by its own method: the device was probed over SSH dozens
of times inside the window being measured, and every session wakes CPU and radio. Measuring
while touching what you measure is not measuring.

Use the coulomb counter, not the percentage:

```
/sys/class/power_supply/battery/charge_counter   µAh, continuous
/sys/class/power_supply/battery/charge_full      µAh total
```

The percentage moves in steps of ~35,000 µAh; a one-hour window has a quantisation error
larger than the signal. With `charge_counter`, 60 minutes suffice. A local sampler writing to
a file, with nobody connected until the end, is the only clean method. `dumpsys batterystats
--reset` before the window makes the report say **which uids** consumed — the difference
between "it uses 4 %/h" and "it uses 4 %/h because of this".

### Two 50-minute windows, same method, nobody connected

| | charge/h | %/h | voltage | energy/h |
|---|---|---|---|---|
| **Printing** (99 → 94 %) | 209.7 mAh | **5.99** | ~4.05 V | ~849 mWh |
| **Idle** (48 → 42 %) | 262.2 mAh | **7.49** | ~3.72 V | ~975 mWh |

**Idle cost more than printing**, and it is not a unit artefact — the inversion survives
conversion to energy. Worse, the idle window ran *after* airplane mode, Bluetooth and NFC off
and three package removals. There is no measured explanation. The suspect is state of charge:
the two windows ran in very different bands (99–94 % against 48–42 %), and fuel gauges are
notoriously imprecise near the extremes. That is a hypothesis, not a measurement; repeating
both windows in similar bands, keeping the raw samples, would settle it.

A related trap: the average of `current_now` samples gave 179 mA where the coulomb counter
registered 262 mAh/h — a 46 % disagreement. One sample per minute misses the peaks; the
counter integrates everything. Do not compute consumption from sampled current.

The battery barely warmed: 21.4 → 22.6 °C over 50 minutes of printing, with the phone beside
the printer rather than mounted on top of it.

### The hub with a power-delivery input

```
status: charging   charge_type: Fast
~1030 mA net inflow, with the CH340 present on the bus
38 % -> 100 % in ~2 h
```

The phone charges and serves as USB host at the same time. Autonomy stopped being an
operational constraint: ~1030 mA in against ~210 mA out while printing. The same hub brings a
USB Ethernet adapter (also a WCH chip — one the kernel *does* have a driver for), recognised
out of the box.

## What did not close

* **`bytes_retransmit` is unstable between runs** — 0, 23 and 16 in three runs where the
  reference host shows 9 over months. With `bytes_invalid=0` and `rttvar=1 ms` it does not look
  like corruption; it looks like the retransmit timeout. Only more load will tell.
* **`bytes_invalid` has no identified cause.** Across two prints it scaled with **time**
  (1.35–1.70 per minute), not with data volume — so it is not link corruption. Which periodic
  event produces it is still open.
