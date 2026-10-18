"""Sling aiming: release the pull when the yellow face passes over the red target.

Measured on a 60 fps recording (540 px wide): the face swings x=101..402 with a half period
of 0.901 s (sinusoid, slow at the ends); the red x2 target sits at x~158 (left side).
Screen captures take ~1 s, so we read the face once (x plus which way it moves is unknown from one
frame -> use two frames), fit the phase, then release with a precisely timed `motionevent UP`.
"""
import math
import subprocess
import time

import cv2
import numpy as np

ADB = r"D:\dice_dreams\tools\platform-tools\adb.exe"
SCALE = 1080 / 540          # recording was 540 px wide; screenshots are 1080 px wide
X_MIN, X_MAX = 101 * SCALE, 402 * SCALE
HALF = 0.901                # seconds from one end to the other
TARGET_X = 158 * SCALE
BAR_Y = (0, 520)            # top bar rows in a 1080x2340 screenshot


def sling_visible(img):
    """True while the slingshot (maroon strap, left side) is on screen, i.e. nothing was fired."""
    c = img[1480:1620, 20:220].astype(int)
    b, g, r = c[..., 0], c[..., 1], c[..., 2]
    return float(((r > 90) & (r < 170) & (g < 75) & (b > 50) & (b < 120) & (r > g * 1.8)).mean()) > 0.2


def find_x(img):
    """x of the yellow face and of the red target in a full screenshot, or (None, None)."""
    hsv = cv2.cvtColor(img[BAR_Y[0]:BAR_Y[1]], cv2.COLOR_BGR2HSV)
    y = cv2.inRange(hsv, (18, 150, 200), (35, 255, 255))
    r = cv2.inRange(hsv, (0, 170, 150), (8, 255, 255)) | cv2.inRange(hsv, (172, 170, 150), (180, 255, 255))
    yy, yx = np.nonzero(y)
    ry, rx = np.nonzero(r)
    fx = float(yx.mean()) if len(yx) > 400 else None
    tx = float(rx.mean()) if len(rx) > 1500 else None
    return fx, tx


def phase_of(x):
    """Phase in [0, pi] for a position on the way right (0 = at X_MIN, pi = at X_MAX)."""
    mid, amp = (X_MIN + X_MAX) / 2, (X_MAX - X_MIN) / 2
    return math.acos(max(-1.0, min(1.0, -(x - mid) / amp)))


def x_at(t, t0, direction0, x0):
    """Predict x at time t given x0 at t0 and direction0 (+1 right, -1 left)."""
    mid, amp = (X_MIN + X_MAX) / 2, (X_MAX - X_MIN) / 2
    ph = phase_of(x0)                      # 0 at left end .. pi at right end
    theta0 = ph if direction0 > 0 else 2 * math.pi - ph
    theta = theta0 + math.pi / HALF * (t - t0)
    return mid - amp * math.cos(theta)


def next_hit_time(t_now, t0, direction0, x0, target_x=None):
    """First time >= t_now when the predicted face x equals the target x (scan at 1 ms).
    The target position changes from round to round, so pass the one read from the screen."""
    target_x = TARGET_X if target_x is None else target_x
    t = t_now
    prev = x_at(t, t0, direction0, x0) - target_x
    while t < t_now + 4 * HALF:
        t += 0.001
        cur = x_at(t, t0, direction0, x0) - target_x
        if prev * cur <= 0:
            return t
        prev = cur
    return None
