# Minimal static server for Mainsail, with SPA fallback.
# Exists because Termux's nginx does not link (it needs a newer OpenSSL than the
# one installed) and upgrading OpenSSL would risk sshd, the only way into the device.
# Tornado is already present in Moonraker's virtualenv.
import tornado.ioloop, tornado.web, os
ROOT = "/data/data/com.termux/files/home/mainsail"
class SPA(tornado.web.StaticFileHandler):
    def validate_absolute_path(self, root, absolute_path):
        if not os.path.exists(absolute_path):
            return os.path.join(root, "index.html")
        return super().validate_absolute_path(root, absolute_path)
app = tornado.web.Application([(r"/(.*)", SPA, {"path": ROOT, "default_filename": "index.html"})])
app.listen(8080, address="0.0.0.0")
print("mainsail on 0.0.0.0:8080", flush=True)
tornado.ioloop.IOLoop.current().start()
