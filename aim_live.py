"""Aim the sling from a live 60 fps stream: hold the pull, track the face, release over the target.

Frames are 540x1170. The yellow face swings x=101..402 (half period ~0.9 s, sinusoid). We fit the
phase from ~1 s of live samples, predict the next time the face crosses the red target and send the
release early by T_OFF (adb delivery + render + stream lag). After the shot we read where the face
really was at release (last frame before the bar vanishes) and correct T_OFF for the next shot.
"""
import json
import math
import os
import subprocess
import time

import cv2
import numpy as np

from stream import ADB, Stream

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
MID, AMP = 268.9, 193.2          # face x range 75.7..462.1 in 540-wide frames (largest-blob centroid)
HALF0 = 0.900
T_OFF_FILE = os.path.join(BASE_DIR, "shots", "t_off.json")
BAR_ROWS = 260


def load_t_off():
    try:
        return float(json.load(open(T_OFF_FILE))["t_off"])
    except Exception:
        return 0.25


def save_t_off(v):
    try:
        json.dump({"t_off": v}, open(T_OFF_FILE, "w"))
    except Exception:
        pass


def _biggest(mask, min_area):
    """Centroid x of the largest blob (falling coins are small yellow blobs; the face is big)."""
    n, _, stats, cent = cv2.connectedComponentsWithStats(mask, connectivity=8)
    best = None
    for i in range(1, n):
        a = stats[i, cv2.CC_STAT_AREA]
        if a >= min_area and (best is None or a > best[0]):
            best = (a, float(cent[i][0]))
    return best[1] if best else None


def face_target(img):
    hsv = cv2.cvtColor(img[:BAR_ROWS], cv2.COLOR_BGR2HSV)
    y = cv2.inRange(hsv, (18, 150, 200), (35, 255, 255))
    y = cv2.morphologyEx(y, cv2.MORPH_OPEN, np.ones((3, 3), np.uint8))
    r = cv2.inRange(hsv, (0, 170, 150), (8, 255, 255)) | cv2.inRange(hsv, (172, 170, 150), (180, 255, 255))
    return _biggest(y, 450), _biggest(r, 900)


def motion(action, x, y):
    return subprocess.Popen([ADB, "shell", "input", "motionevent", action, str(x), str(y)],
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def fit_phase(ts, xs, half):
    """Best phase phi for x = MID + AMP*cos(pi/half*t + phi); returns (phi, rms)."""
    w = math.pi / half
    ts, xs = np.asarray(ts), np.asarray(xs)
    best = (None, 1e18)
    for phi in np.arange(0, 2 * math.pi, 0.01):
        res = xs - (MID + AMP * np.cos(w * ts + phi))
        e = float(np.median(np.abs(res)))
        if e < best[1]:
            best = (phi, e)
    return best


def next_cross(phi, half, tgt, t_min):
    w = math.pi / half
    c = max(-1.0, min(1.0, (tgt - MID) / AMP))
    a = math.acos(c)
    cands = []
    for base in (a, -a):
        k = math.floor((w * t_min + phi - base) / (2 * math.pi)) - 1
        for kk in range(k, k + 4):
            t = (base + 2 * math.pi * kk - phi) / w
            if t >= t_min:
                cands.append(t)
    return min(cands) if cands else None


def aim_and_release(log=print, sling_xy=(540, 1640, 1800, 1950)):
    """Run the whole hold / track / release. Returns a dict of measurements for tuning."""
    t_off = load_t_off()
    st = Stream()
    t0 = time.perf_counter()
    while st.get() is None and time.perf_counter() - t0 < 6:
        time.sleep(0.01)
    x, y0, y1, y2 = sling_xy
    motion("DOWN", x, y0).wait()
    time.sleep(0.12)
    motion("MOVE", x, y1).wait()
    time.sleep(0.12)
    motion("MOVE", x, y2).wait()
    # collect live samples
    ts, xs, tgs = [], [], []
    last_count = -1
    t_start = time.perf_counter()
    result = {"ok": False}
    try:
        while time.perf_counter() - t_start < 2.4:
            fr = st.get()
            if fr is None or st.count == last_count:
                time.sleep(0.002)
                continue
            last_count = st.count
            t, img = fr
            fx, tx = face_target(img)
            if tx is not None:
                tgs.append(tx)
            if fx is not None:
                ts.append(t - t_start)
                xs.append(fx)
            if len(xs) >= 70 and ts[-1] - ts[0] > 1.05:
                break
        if len(xs) < 30 or not tgs:
            log("aim_live: not enough samples (%d face, %d target) -> release now" % (len(xs), len(tgs)))
            motion("UP", x, y2).wait()
            return result
        tgt = float(np.median(tgs))
        # robust half-period + phase over a small grid
        half = HALF0                 # measured 0.901 s on every swing; only the phase is unknown
        phi, err = fit_phase(ts, xs, half)
        now = time.perf_counter() - t_start
        t_cross = next_cross(phi, half, tgt, now + t_off + 0.06)
        w = math.pi / half
        log("aim_live: samples=%d tgt=%.0f half=%.3f fit_err=%.1fpx t_off=%.3f" % (len(xs), tgt, half, err, t_off))
        if err > 25 or t_cross is None:
            log("aim_live: poor fit -> release now")
            motion("UP", x, y2).wait()
            return result
        t_send = t_cross - t_off
        while time.perf_counter() - t_start < t_send - 0.004:
            time.sleep(0.001)
        while time.perf_counter() - t_start < t_send:
            pass
        t_up = time.perf_counter() - t_start
        motion("UP", x, y2).wait()
        # watch the stream until the bar disappears: last face frame = face position at release
        last_face = (None, None)
        gone = 0
        traj = []
        t_end = time.perf_counter() + 3.0
        last_count = st.count
        while time.perf_counter() < t_end:
            fr = st.get()
            if fr is None or st.count == last_count:
                time.sleep(0.002)
                continue
            last_count = st.count
            t, img = fr
            fx, _ = face_target(img)
            traj.append((round(t - t_start, 3), None if fx is None else round(fx, 1)))
            if fx is not None:
                last_face = (t - t_start, fx)
                gone = 0
            else:
                gone += 1
                if gone >= 4 and last_face[0] is not None and last_face[0] > t_up:
                    break
        try:
            json.dump({"t_up": t_up, "t_cross": t_cross, "tgt": tgt, "phi": phi, "half": half,
                       "t_off": t_off, "traj": traj},
                      open(os.path.join(BASE_DIR, "shots", "aim_traj.json"), "w"))
        except Exception:
            pass
        result.update(ok=True, t_up=t_up, t_cross=t_cross, last_face=last_face, tgt=tgt, phi=phi, half=half)
        # The face keeps swinging ~0.2 s after our release command (adb + render lag), then FREEZES where
        # the shot was taken; the bar stays on screen ~0.7 s longer. The freeze point is the real hit.
        frozen = None
        pts = [(t, x) for t, x in traj if x is not None and t > t_up]
        for k in range(len(pts) - 3):
            if all(abs(pts[k + j][1] - pts[k][1]) < 1.2 for j in range(1, 4)):
                frozen = pts[k]
                break
        if frozen is None:
            log("aim_live: released at %.3f (cross %.3f); face never froze, no calibration" % (t_up, t_cross))
        else:
            tl, xl = frozen
            th = w * tl + phi
            v = -AMP * w * math.sin(th)                       # px/s of the face at the freeze
            err_px = xl - tgt
            err_t = err_px / v if abs(v) > 60 else 0.0        # >0: stopped past the target (released too late)
            result.update(err_t=err_t, err_px=err_px)
            log("aim_live: released at %.3f (cross %.3f); froze at x=%.0f (target %.0f, %+.0f px) at %.3f; "
                "timing error %+.3f s" % (t_up, t_cross, xl, tgt, err_px, tl, err_t))
            # err_t > 0 -> release earlier next time (bigger t_off); damped, clamped
            corr = max(-0.1, min(0.1, err_t))
            save_t_off(max(0.05, min(0.6, t_off + corr * 0.7)))
    finally:
        st.close()
    return result


if __name__ == "__main__":
    print(aim_and_release())
