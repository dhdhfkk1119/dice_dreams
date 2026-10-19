"""Offline check of face tracking + phase fit on the 60 fps recording."""
import math
import os

import cv2
import numpy as np

import aim_live as al

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
cap = cv2.VideoCapture(os.path.join(BASE_DIR, "shots", "r.mp4"))
fps = cap.get(cv2.CAP_PROP_FPS)
ts, xs, tg = [], [], []
i = 0
while True:
    ok, f = cap.read()
    if not ok:
        break
    fx, tx = al.face_target(f)
    if fx is not None:
        ts.append(i / fps)
        xs.append(fx)
    if tx is not None:
        tg.append(tx)
    i += 1
ts, xs = np.array(ts), np.array(xs)
print("face samples", len(xs), "target samples", len(tg), "target median", np.median(tg))
sel = (ts > 2.4) & (ts < 11)
print("face x range", xs[sel].min().round(), xs[sel].max().round())
# fit a 1.05 s window, as the live code does, and check how well it predicts the following 3 s
for start in (2.6, 4.0, 5.5, 7.0):
    w = (ts >= start) & (ts < start + 1.05)
    best = min(((al.fit_phase(ts[w] - start, xs[w], h), h) for h in (0.901,)), key=lambda a: a[0][1])
    (phi, err), half = best
    fut = (ts >= start + 1.05) & (ts < start + 4.0)
    pred = al.MID + al.AMP * np.cos(math.pi / half * (ts[fut] - start) + phi)
    print("window %.1fs: fit err %.1f px, half %.3f; prediction error over next 3 s: median %.1f px, max %.1f px" % (
        start, err, half, np.median(np.abs(pred - xs[fut])), np.abs(pred - xs[fut]).max()))
