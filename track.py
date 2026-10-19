"""Track the yellow face marker and the red target on the sling top bar in a screen recording."""
import os
import sys

import cv2
import numpy as np

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
path = sys.argv[1] if len(sys.argv) > 1 else os.path.join(BASE_DIR, "shots", "r.mp4")
cap = cv2.VideoCapture(path)
fps = cap.get(cv2.CAP_PROP_FPS)
xs, tg = [], []
while True:
    ok, f = cap.read()
    if not ok:
        break
    hsv = cv2.cvtColor(f[0:260], cv2.COLOR_BGR2HSV)
    y = cv2.inRange(hsv, (18, 150, 200), (35, 255, 255))
    r = cv2.inRange(hsv, (0, 170, 150), (8, 255, 255)) | cv2.inRange(hsv, (172, 170, 150), (180, 255, 255))
    yy, yx = np.nonzero(y)
    ry, rx = np.nonzero(r)
    xs.append(float(yx.mean()) if len(yx) > 120 else np.nan)
    tg.append(float(rx.mean()) if len(rx) > 400 else np.nan)
xs, tg = np.array(xs), np.array(tg)
print("fps", fps, "frames", len(xs), "valid face", int(np.isfinite(xs).sum()), "valid target", int(np.isfinite(tg).sum()))
print("target x median", np.nanmedian(tg), "face x range", np.nanmin(xs), np.nanmax(xs))
np.save(os.path.join(BASE_DIR, "shots", "face.npy"), xs)
np.save(os.path.join(BASE_DIR, "shots", "tgt.npy"), tg)
for i in range(0, len(xs), 30):
    fx = "-" if np.isnan(xs[i]) else round(xs[i])
    tx = "-" if np.isnan(tg[i]) else round(tg[i])
    print(i, round(i / fps, 2), fx, tx)
