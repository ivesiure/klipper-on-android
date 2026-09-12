# Patches

Three small changes, none of which upstream has (see `docs/en/decisions.md` for why they were
not submitted). They are a rebuild recipe: apply them, then **verify** they went in before
starting anything, because the failure they prevent in `statistics.py` only shows up one
second after `Loaded MCU`.

| File | Target | What it fixes |
|---|---|---|
| `klipper-android.diff` | `klippy/chelper/__init__.py` | `-lm` in `COMPILE_ARGS`. Bionic does not resolve `libm` implicitly; the C helper compiles and then fails at `dlopen` with `cannot locate symbol "atan2"` |
| `klipper-android.diff` | `klippy/extras/statistics.py` | `os.getloadavg()` does not exist on Android. Falls back to `/proc/loadavg`, which does |
| `moonraker-android.diff` | `moonraker/components/proc_stats.py` | `/sys/class/hwmon/` exists but cannot be opened by an app process; `isdir()` passes, `scandir()` raises, Moonraker dies on load. Checks `os.access` first |

```bash
git -C klipper apply patches/klipper-android.diff
git -C moonraker apply patches/moonraker-android.diff

grep -q -- '-lm' klipper/klippy/chelper/__init__.py        && echo "patch 1 ok" || echo "PATCH 1 MISSING"
grep -q 'proc/loadavg' klipper/klippy/extras/statistics.py  && echo "patch 2 ok" || echo "PATCH 2 MISSING"
grep -q '_hwmon_ok' moonraker/moonraker/components/proc_stats.py && echo "patch 3 ok" || echo "PATCH 3 MISSING"
```

The Klipper diff was made against a fork pinned to a specific commit; if `git apply` refuses,
the hunks are small enough to apply by hand. The Moonraker one is a plain unified diff with
approximate line numbers for the same reason — `patch -p1 --fuzz` or by hand.
