import cv2
import numpy as np

import aim_live as al

cap = cv2.VideoCapture(r"D:\dice_dreams\shots\r.mp4")
fps = cap.get(cv2.CAP_PROP_FPS)
ts, xs = [], []
i = 0
while True:
    ok, f = cap.read()
    if not ok:
        break
    fx, _ = al.face_target(f)
    if fx is not None:
        ts.append(i / fps)
        xs.append(fx)
    i += 1
ts, xs = np.array(ts), np.array(xs)
sel = (ts > 2.3) & (ts < 11.2)
t, x = ts[sel], xs[sel]
print("x percentiles 1/99:", np.percentile(x, 1).round(1), np.percentile(x, 99).round(1))
# turning points
k = 7
sm = np.convolve(x, np.ones(k) / k, mode="same")
pts = []
for j in range(k, len(sm) - k):
    if (sm[j] == sm[j - k:j + k + 1].max() or sm[j] == sm[j - k:j + k + 1].min()) and (not pts or t[j] - pts[-1][0] > 0.4):
        pts.append((t[j], sm[j]))
print("turning points:", [(round(a, 2), round(b)) for a, b in pts])
g = np.diff([p[0] for p in pts])
print("half periods:", g.round(3), "median", np.median(g).round(4))
hi = np.median([p[1] for p in pts if p[1] > 260])
lo = np.median([p[1] for p in pts if p[1] < 260])
print("ends: lo %.1f hi %.1f -> MID %.1f AMP %.1f" % (lo, hi, (lo + hi) / 2, (hi - lo) / 2))
