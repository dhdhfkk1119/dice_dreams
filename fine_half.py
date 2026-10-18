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
sel = (ts > 2.4) & (ts < 11.0)
t, x = ts[sel] - 2.4, xs[sel]
best = None
for half in np.arange(0.890, 0.912, 0.0005):
    phi, err = al.fit_phase(t, x, half)
    if best is None or err < best[1]:
        best = (half, err, phi)
print("best half %.4f  err %.2f px  (fps %.3f)" % (best[0], best[1], fps))
