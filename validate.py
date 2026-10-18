import numpy as np

import sling

fps = 59.93
xs = np.load(r"D:\dice_dreams\shots\face.npy") * sling.SCALE
t = np.arange(len(xs)) / fps
ok = np.isfinite(xs) & (t > 2.4) & (t < 11.0)
idx = np.nonzero(ok)[0]
errs = []
for start in range(0, len(idx) - 200, 40):
    i0 = idx[start]
    # two frames ~1.0 s apart as the bot would have: infer the direction from the sign of the change
    i1 = idx[min(start + 20, len(idx) - 1)]
    dx = xs[i1] - xs[i0]
    d0 = 1 if dx > 0 else -1
    # the model needs x0 and direction at t0 = time of the second frame
    x0, t0 = xs[i1], t[i1]
    # direction at the second frame: approximate by sign of the last small step
    d1 = 1 if xs[i1] - xs[idx[start + 19]] > 0 else -1
    for k in (60, 120, 180):
        j = idx[min(start + 20 + k, len(idx) - 1)]
        pred = sling.x_at(t[j], t0, d1, x0)
        errs.append(abs(pred - xs[j]))
errs = np.array(errs)
print("prediction error px (1080 scale): median %.1f  p90 %.1f  max %.1f  (n=%d)" % (
    np.median(errs), np.percentile(errs, 90), errs.max(), len(errs)))
tx = sling.TARGET_X
print("target x (1080 scale)", round(tx), "; one px error ~ %.1f ms near target (speed ~900 px/s)" % (1000 / 900))
