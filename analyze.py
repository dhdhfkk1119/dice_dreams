import os

import numpy as np

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
fps = 59.93
xs = np.load(os.path.join(BASE_DIR, "shots", "face.npy"))
tg = np.load(os.path.join(BASE_DIR, "shots", "tgt.npy"))
ok = np.isfinite(xs)
t = np.arange(len(xs)) / fps
seg = ok & (t > 2.3) & (t < 11.4)
tt, xx = t[seg], xs[seg]
print("samples", seg.sum(), "t", tt.min().round(2), tt.max().round(2))
# turning points: local min/max of a lightly smoothed signal
k = 5
sm = np.convolve(xx, np.ones(k) / k, mode="same")
d = np.diff(sm)
turn = [i for i in range(2, len(d) - 2) if d[i - 1] * d[i + 1] < 0 and abs(sm[i] - sm[0]) > 0]
pts = []
for i in turn:
    if not pts or tt[i] - pts[-1][0] > 0.3:
        pts.append((tt[i], sm[i]))
print("turning points (t, x):", [(round(a, 2), round(b)) for a, b in pts])
gaps = np.diff([p[0] for p in pts])
print("half periods", gaps.round(3))
print("speed px/s (|dx|/gap):", (np.abs(np.diff([p[1] for p in pts])) / gaps).round(0))
# crossings of the target x
tx = float(np.nanmedian(tg[ok]))
cross = []
for i in range(1, len(xx)):
    if (xx[i - 1] - tx) * (xx[i] - tx) < 0 and tt[i] - tt[i - 1] < 0.1:
        cross.append((tt[i], "L" if xx[i] < xx[i - 1] else "R"))
print("target x", round(tx), "crossings", [(round(a, 2), b) for a, b in cross])
# speed profile vs position (is it a sinusoid, i.e. slower at the ends?)
v = np.abs(np.diff(xx)) / np.diff(tt)
pos = (xx[1:] + xx[:-1]) / 2
for lo, hi in [(100, 150), (150, 200), (200, 250), (250, 300), (300, 350), (350, 410)]:
    m = (pos >= lo) & (pos < hi) & (np.diff(tt) < 0.05)
    print(f"x {lo}-{hi}: median speed {np.median(v[m]) if m.any() else float('nan'):.0f} px/s (n={m.sum()})")
