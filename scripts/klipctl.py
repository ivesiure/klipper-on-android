# Talks to klippy over its API socket (the -a of klippy.py), bypassing Moonraker.
# Useful to check state and send gcode when there is no interface -- it is how the
# load tests were driven. Read-only unless you send it a gcode.
#
# usage:  python klipctl.py "G28"           sends gcode and waits for it to finish
#         from klipctl import send          send("info"), send("objects/query", {...})
import socket, json, sys, time
SOCK = "/data/data/com.termux/files/home/pdata/run/klipper.sock"
def send(method, params=None, timeout=300):
    s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM); s.settimeout(timeout)
    s.connect(SOCK)
    s.sendall(json.dumps({"id": 1, "method": method, "params": params or {}}).encode() + b"\x03")
    buf = b""; t0 = time.time()
    while b"\x03" not in buf:
        if time.time() - t0 > timeout: return {"error": "local timeout"}
        c = s.recv(65536)
        if not c: break
        buf += c
    s.close()
    return json.loads(buf.split(b"\x03")[0].decode())
if __name__ == "__main__":
    script = sys.argv[1]
    to = float(sys.argv[2]) if len(sys.argv) > 2 else 300
    t0 = time.time()
    r = send("gcode/script", {"script": script}, timeout=to)
    print("%.1fs" % (time.time() - t0), json.dumps(r)[:600])
