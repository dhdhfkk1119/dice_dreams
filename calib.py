"""Calibrate: stream fps and tap -> visible-in-stream latency (on the lobby, harmless taps)."""
import statistics
import subprocess
import time

import numpy as np

from stream import ADB, Stream

s = Stream()
t0 = time.perf_counter()
while s.get() is None and time.perf_counter() - t0 < 10:
    time.sleep(0.02)
print("first frame after %.2f s" % (time.perf_counter() - t0))
time.sleep(2)
c0 = s.count
time.sleep(3)
print("stream fps ~ %.1f" % ((s.count - c0) / 3))
lat = []
for i in range(6):
    time.sleep(1.6)
    t, base = s.get()
    # toggle the xN badge (harmless); watch the badge region change in the stream
    x, y = 763 // 2, 1915 // 2
    roi = (slice(y - 25, y + 25), slice(x - 30, x + 30))
    ref = base[roi].astype(int)
    t_send = time.perf_counter()
    subprocess.run([ADB, "shell", "input", "tap", "763", "1915"], capture_output=True)
    t_ret = time.perf_counter()
    seen = None
    while time.perf_counter() - t_send < 3:
        tt, f = s.get()
        if tt > t_send and np.abs(f[roi].astype(int) - ref).mean() > 12:
            seen = tt
            break
        time.sleep(0.005)
    if seen:
        lat.append(seen - t_send)
        print("tap %d: adb returned after %.3f s, visible in stream after %.3f s" % (i, t_ret - t_send, seen - t_send))
    else:
        print("tap", i, "no change seen")
if lat:
    print("round-trip latency: median %.3f  min %.3f  max %.3f" % (statistics.median(lat), min(lat), max(lat)))
s.close()
