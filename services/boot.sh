#!/data/data/com.termux/files/usr/bin/sh
# Brings the printer stack up when the phone boots. Run by the Termux:Boot add-on
# from ~/.termux/boot/.
#
# sshd comes FIRST, on purpose. It is not under runit (the packaged sshd/ service
# ships with a "down" file) and had no boot mechanism at all: without this line a
# reboot leaves the device without remote access and without remote repair. If
# everything else fails, there is still a way in.
#
# The wake-lock is mandatory: without it Android suspends the processes.

pgrep -x sshd >/dev/null 2>&1 || sshd

termux-wake-lock

# A service directory of OUR OWN, not the system's $PREFIX/var/service.
# That one belongs to packages: openssh installs sshd/ and ssh-agent/, nginx
# installs nginx/, all with a log/run pointing at /sv/<name>, a path that does
# not exist here. svlogd dies, runsv resurrects it, and that loop burned 22 min
# of CPU in 14 h -- against 3.6 s for our whole stack. Deleting them only lasts
# until the next `pkg upgrade` recreates them. Supervising only our own
# directory solves it for good.
pgrep -f "[r]unsvdir" >/dev/null 2>&1 || exec runsvdir /data/data/com.termux/files/home/pdata/sv
