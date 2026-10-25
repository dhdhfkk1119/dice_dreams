"""Learn which corner buttons close / skip an ad.

Library: D:\\dice_dreams\\ad_buttons\\*.png  (white-glyph masks of buttons that led out of an ad: X, >>, ▶|, ...)
         D:\\dice_dreams\\ad_buttons\\bad\\*.png (corner things that only opened the store: never press again)
Unknown ad: candidate corner glyphs are tried one by one; a press that gets us out of the ad (or reveals a known
exit button) is saved to the library, so the next ad with that button is closed at once.
"""
import glob
import os
import time

import cv2
import numpy as np

import cvio

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
LIB = os.path.join(BASE_DIR, "ad_buttons")
BAD = os.path.join(LIB, "bad")
CAND = os.path.join(LIB, "candidates")   # glyphs that coincided with leaving an ad: for review, never used
SCALES = (0.6, 0.75, 0.9, 1.0, 1.2, 1.5, 1.8, 2.2, 2.6, 3.0)
BAND = (40, 330)          # rows of the top band that hold the ad's buttons
THR = 0.72
os.makedirs(BAD, exist_ok=True)
os.makedirs(CAND, exist_ok=True)

_lib, _bad = [], []


def reload():
    global _lib, _bad
    _lib = [(os.path.basename(p), cvio.imread(p, 0)) for p in sorted(glob.glob(os.path.join(LIB, "*.png")))]
    _bad = [(os.path.basename(p), cvio.imread(p, 0)) for p in sorted(glob.glob(os.path.join(BAD, "*.png")))]
    _lib = [(n, g) for n, g in _lib if g is not None]
    _bad = [(n, g) for n, g in _bad if g is not None]


reload()


def mask_of(img, lo=BAND[0], hi=BAND[1], thr=200):
    return (img[lo:hi].min(axis=2) > thr).astype(np.uint8) * 255


def _best(band, glyph, thr, y_offset=BAND[0]):
    best = None
    for s in SCALES:
        t = cv2.resize(glyph, None, fx=s, fy=s, interpolation=cv2.INTER_AREA if s < 1 else cv2.INTER_LINEAR)
        if t.shape[0] < 14 or t.shape[0] >= band.shape[0] or t.shape[1] >= band.shape[1]:
            continue
        r = cv2.matchTemplate(band, t, cv2.TM_CCOEFF_NORMED)
        _, mx, _, loc = cv2.minMaxLoc(r)
        if mx >= thr and (best is None or mx > best[0]):
            best = (mx, loc[0] + t.shape[1] // 2, loc[1] + t.shape[0] // 2 + y_offset)
    return best


def find_known(img, thr=THR):
    """Best learned exit glyph in an ad corner -> (x, y, name) or None."""
    h, w = img.shape[:2]
    if w > h:
        x_edge, y_edge = round(w * 0.22), round(h * 0.38)
        regions = (
            (0, 0, x_edge, y_edge),
            (w - x_edge, 0, w, y_edge),
            (w - x_edge, h - y_edge, w, h),
        )
        best = None
        for name, glyph in _lib:
            for x0, y0, x1, y1 in regions:
                band = mask_of(img[y0:y1, x0:x1], 0, y1 - y0)
                match = _best(band, glyph, thr, y_offset=y0)
                if match:
                    candidate = (match[0], match[1] + x0, match[2], name)
                    if best is None or candidate[0] > best[0]:
                        best = candidate
        return None if best is None else best[1:]

    band = mask_of(img)
    best = None
    for name, g in _lib:
        b = _best(band, g, thr)
        if b and (best is None or b[0] > best[0]):
            best = (b[0], b[1], b[2], name)
    if best is None:
        return None
    _, x, y, name = best
    w = img.shape[1]
    if 0.11 * w < x < 0.85 * w:  # only corners count (scale-invariant: works in portrait or a rotated/landscape ad)
        return None
    return x, y, name


def candidates(img, tried=()):
    """Compact bright glyphs in the top corners, right corner first: [(x, y, w, h)], skipping the ones tried."""
    lo, hi = 40, 520        # top band, where ads put their buttons (a little lower on some layouts)
    m = mask_of(img, lo, hi, 190)
    m[:, 360:720] = 0
    d = cv2.dilate(m, np.ones((9, 9), np.uint8))
    n, _, stats, cent = cv2.connectedComponentsWithStats(d, connectivity=8)
    out = []
    for i in range(1, n):
        x, y, w, h, a = stats[i]
        w, h = w - 8, h - 8                      # undo the dilation
        if not (14 <= w <= 64 and 14 <= h <= 64):
            continue
        raw = int((m[y:y + stats[i][3], x:x + stats[i][2]] > 0).sum())
        if raw < 25:
            continue
        cx, cy = int(cent[i][0]), int(cent[i][1]) + lo
        if any(abs(cx - tx) < 40 and abs(cy - ty) < 40 for tx, ty in tried):
            continue
        right = 0 if cx > 720 else 1
        out.append((right, abs(cy - 180), cx, cy, w, h))
    out.sort()
    cands = [(cx, cy, w, h) for _, _, cx, cy, w, h in out]
    # skip things already known to be useless (they opened the store)
    keep = []
    for cx, cy, w, h in cands:
        crop = _crop_mask(img, cx, cy, w, h)
        if crop is not None and any(_same(crop, g) for _, g in _bad):
            continue
        keep.append((cx, cy, w, h))
    return keep[:6]


def _crop_mask(img, cx, cy, w, h):
    x0, x1 = max(0, cx - w // 2 - 3), min(img.shape[1], cx + w // 2 + 4)
    y0, y1 = max(0, cy - h // 2 - 3), min(img.shape[0], cy + h // 2 + 4)
    if x1 - x0 < 14 or y1 - y0 < 14:
        return None
    return (img[y0:y1, x0:x1].min(axis=2) > 190).astype(np.uint8) * 255


def _same(a, b, thr=0.85):
    """True when mask b (resized to a's size) is found inside mask a with a few pixels of slack."""
    if a.shape[0] < 6 or b.shape[0] < 6:
        return False
    bb = cv2.resize(b, (a.shape[1], a.shape[0]), interpolation=cv2.INTER_AREA)
    pad = cv2.copyMakeBorder(a, 6, 6, 6, 6, cv2.BORDER_CONSTANT, value=0)
    r = cv2.matchTemplate(pad, bb, cv2.TM_CCOEFF_NORMED)
    return float(r.max()) >= thr


def _save(img, cx, cy, w, h, folder, tag):
    crop = _crop_mask(img, cx, cy, w, h)
    if crop is None:
        return None
    others = _lib if folder == LIB else _bad
    if any(_same(crop, g) for _, g in others):
        return None                       # already known
    path = os.path.join(folder, f"{tag}_{time.strftime('%H%M%S')}.png")
    cv2.imwrite(path, crop)
    reload()
    return path


def learn_exit(img, cand):
    """This corner glyph coincided with leaving the ad. Timing coincidences (countdown "6s", mute icon) fooled the
    automatic learning, so it is only filed under candidates/ for a human look, not used by the bot."""
    crop = _crop_mask(img, *cand[:2], cand[2], cand[3])
    if crop is None:
        return None
    path = os.path.join(CAND, f"cand_{time.strftime('%H%M%S')}.png")
    cv2.imwrite(path, crop)
    return path


def learn_bad(img, cand):
    """This corner glyph only opened the store: never press it again."""
    return _save(img, *cand, BAD, "bad")


DIALOG_X = cvio.imread(os.path.join(BASE_DIR, "dialogx_glyph.png"), 0)   # black X on a white dialog (ad feedback, offers, ...)


def find_dialog_x(img, thr=0.72):
    """Black X in the top-right of a white dialog -> (x, y) or None."""
    if DIALOG_X is None:
        return None
    r0, r1, c0 = 300, 1700, 400
    reg = img[r0:r1, c0:]
    dark = (reg.max(axis=2) < 90).astype(np.uint8) * 255
    best = None
    for s in (0.5, 0.65, 0.8, 1.0, 1.25, 1.5):
        t = cv2.resize(DIALOG_X, None, fx=s, fy=s, interpolation=cv2.INTER_AREA if s < 1 else cv2.INTER_LINEAR)
        if t.shape[0] < 14:
            continue
        r = cv2.matchTemplate(dark, t, cv2.TM_CCOEFF_NORMED)
        _, mx, _, loc = cv2.minMaxLoc(r)
        if mx >= thr and (best is None or mx > best[0]):
            cx, cy = loc[0] + t.shape[1] // 2 + c0, loc[1] + t.shape[0] // 2 + r0
            ring = img[max(0, cy - 60):cy + 60, max(0, cx - 60):cx + 60]
            if float((ring.min(axis=2) > 225).mean()) > 0.6:     # sits on white
                best = (mx, cx, cy)
    return (best[1], best[2]) if best else None


def is_bad(img, x, y, size=40):
    """Is the glyph around (x, y) one of the known useless corner buttons (mute, ad info, store openers)?"""
    crop = _crop_mask(img, x, y, size, size)
    return crop is not None and any(_same(crop, g, 0.55) for _, g in _bad)
