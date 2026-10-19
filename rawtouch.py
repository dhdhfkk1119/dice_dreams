"""Low-latency touch injection via sendevent on the phone's touchscreen device (no Java start-up per event).

Raw coordinates are 0..4095 on both axes (getevent -lp), mapped from the 1080x2340 screen.
One persistent `adb shell` is kept open; each call just writes a few lines to its stdin.
"""
import os
import subprocess
import time

ADB = os.path.join(os.path.dirname(os.path.abspath(__file__)), "tools", "platform-tools", "adb.exe")
DEV = "/dev/input/event4"      # sec_touchscreen
W, H = 1080, 2340


def raw(x, y):
    return round(x * 4095 / (W - 1)), round(y * 4095 / (H - 1))


class Touch:
    def __init__(self):
        self.p = subprocess.Popen([ADB, "shell"], stdin=subprocess.PIPE, stdout=subprocess.DEVNULL,
                                  stderr=subprocess.DEVNULL, bufsize=0)
        self.tid = 100

    def _send(self, lines):
        self.p.stdin.write(("; ".join(lines) + "\n").encode())
        self.p.stdin.flush()

    def _ev(self, t, c, v):
        return f"sendevent {DEV} {t} {c} {v}"

    def down(self, x, y):
        rx, ry = raw(x, y)
        self.tid += 1
        self._send([self._ev(3, 57, self.tid), self._ev(3, 53, rx), self._ev(3, 54, ry),
                    self._ev(1, 330, 1), self._ev(0, 0, 0)])

    def move(self, x, y):
        rx, ry = raw(x, y)
        self._send([self._ev(3, 53, rx), self._ev(3, 54, ry), self._ev(0, 0, 0)])

    def up(self):
        self._send([self._ev(3, 57, 4294967295), self._ev(1, 330, 0), self._ev(0, 0, 0)])

    def tap(self, x, y, hold=0.05):
        self.down(x, y)
        time.sleep(hold)
        self.up()

    def close(self):
        try:
            self.p.stdin.write(b"exit\n")
            self.p.stdin.flush()
            self.p.wait(timeout=2)
        except Exception:
            self.p.kill()


if __name__ == "__main__":
    os.environ.setdefault("ANDROID_SERIAL", "R3KL20CWEMT")
    t = Touch()
    t.tap(763, 1915)       # harmless: cycles the xN multiplier badge
    time.sleep(0.5)
    t.close()
    print("sent")
