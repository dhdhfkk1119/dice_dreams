"""Dice Dreams auto player.

Rule: coins >= cheapest building -> build; otherwise ROLL. Stops when energy is 0,
after MAX_ROLLS, or when an unknown screen persists (screenshot saved for review).
Usage: python bot.py [max_rolls]
"""
import os, re, subprocess, sys, time

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# Always talk to the real phone, never to BlueStacks (emulator-5554) or any other device.
# adb reads ANDROID_SERIAL, so every adb call below (also in stream.py / aim_live.py) obeys it.
PHONE_SERIAL = "R3KL20CWEMT"
os.environ["ANDROID_SERIAL"] = PHONE_SERIAL

import adlearn
import aim_live
import cv2
import cvio
import numpy as np
import sling
from rapidocr_onnxruntime import RapidOCR

ADB = os.path.join(BASE_DIR, "tools", "platform-tools", "adb.exe")


def require_phone():
    out = subprocess.run([ADB, "devices"], capture_output=True, text=True).stdout
    if not re.search(rf"^{PHONE_SERIAL}\s+device\b", out, re.M):
        print(f"Phone {PHONE_SERIAL} is not connected (adb devices below). Not touching any other device.\n{out}")
        sys.exit(2)
OUT = os.path.join(BASE_DIR, "shots")
ROLL = (538, 1977)
HAMMER = (948, 2211)
HAMMER_BADGE = (970, 2115, 1055, 2185)  # red badge on the hammer icon: how many upgrades are affordable right now
SCENE = (540, 500)        # empty scene area: closes the build panel
ROLL_WAIT = 1.3  # seconds between ROLL taps
MAX_IDLE = 240  # x 15 s (1 hour) with no energy before giving up
PINBALL_BTNS = [(538, 2042), (228, 2042), (848, 2042)]  # pinball game: the three pink buttons
FIGHT_MOVES = [(197, 2059), (539, 2059), (883, 2059)]  # fist / paper / scissors buttons
ANYWHERE = (540, 1000)
WEEKLY = (111, 527)       # clipboard icon: weekly goals
PAY_CLOSE = [(984, 300), (963, 482), (971, 351), (989, 390), (1000, 200), (1010, 130)]  # top-right X spots
MIN_ENERGY = 3  # one ROLL costs xN energy (x3 -> 3); below this a "buy rolls" offer pops up
BACK_BTN = (98, 281)      # back arrow (top-left) on full-screen event pages
BACK_BTNS = [(98, 281), (105, 349)]  # event pages / the side menu
SAFE_TAPS = [(540, 1000), (540, 1250), (540, 90), (BACK_BTN), (200, 1300), (540, 1000), (800, 1300)]
UNKNOWN_TAPS = [(900, 1000), (540, 1000), (900, 600), (540, 1250), (900, 1400), (540, 700), (200, 1000)]  # right side first
ROLL_BOX = (400, 1830, 680, 2100)
MULT_BTN = (763, 1915)
MULT_BOX = (680, 1878, 860, 1960)  # the xN badge's own number only (kept clear of MAX_BOX above it)
MAX_BOX = (670, 1800, 870, 1878)   # the "MAX xN" bubble: the highest multiplier on offer right now
STEAL = (540, 1919)
TARGET = (532, 819)       # attack: castle pin
SLING = (540, 1640, 540, 2050)  # pull straight down -> bullseye (tested: x1.5 bullseye)
BUTTONS = {"COLLECT", "CLAIM", "OK", "CONTINUE", "NEXT", "AWESOME", "GREAT", "YAY", "COOL", "TAP TO CONTINUE",
           "AMAZING", "FREE", "WOW", "NICE", "PERFECT", "EXCELLENT", "SUPER", "GOT IT", "LET'S GO"}  # green "go on" / free-gift buttons
NEUTRAL = (540, 1450)     # dismisses reward popups
COIN_BOX = (200, 100, 650, 300)
ENERGY_BOX = (250, 2150, 800, 2320)
PRICE_BOX = (0, 2080, 1080, 2260)
BUTTON_Y = 2170

ocr = RapidOCR()
os.makedirs(OUT, exist_ok=True)


def adb(*a):
    return subprocess.run([ADB, *a], capture_output=True)


def shot(name=None):
    """Screenshot; if the phone is unplugged / adb drops, wait for it to come back instead of dying."""
    waited = 0
    while True:
        # raw RGBA (16-byte header + pixels): ~0.7 s over USB, the PNG path takes ~1.6 s (on-phone compression)
        raw = subprocess.run([ADB, "exec-out", "screencap"], capture_output=True).stdout
        img = None
        if len(raw) > 16:
            w, h, fmt = (int(v) for v in np.frombuffer(raw[:12], np.uint32))
            if fmt == 1 and len(raw) == 16 + w * h * 4:
                img = np.ascontiguousarray(np.frombuffer(raw, np.uint8, offset=16).reshape(h, w, 4)[:, :, 2::-1])
        if img is not None:
            return img  # may be landscape (some ads rotate the screen): callers must check landscape(img)
            # before using any fixed pixel coordinate on it - rotating the array here would NOT make taps
            # computed from it land correctly, since the real device is still physically in that orientation
        if waited % 30 == 0:
            log("no screenshot: phone/adb disconnected? waiting...")
        if waited and waited % 60 == 0:
            subprocess.run([ADB, "kill-server"], capture_output=True)
            subprocess.run([ADB, "start-server"], capture_output=True)
        waited += 5
        time.sleep(5)


def landscape(img):
    """True while the screen is rotated (some ads do this): every fixed pixel coordinate in this file assumes
    portrait, so callers must skip tapping anything computed from a landscape frame and just wait it out."""
    return img.shape[0] < img.shape[1]


POST_SHARE = True   # always share a restored kingdom to the story (+10 rolls), as the user asked
BUILD_AT = 500_000  # with energy left, upgrade the kingdom once this many coins are saved (front card first)
_kingdom_changed = False
BUY_ZONE = (250, 1650, 830, 2250)  # where the green price button / ROLL sit (x0, y0, x1, y1)
BUY_LOCK_S = 6.0                   # seconds the zone stays locked after a payment screen was seen
_buy_lock_until = 0.0


def lock_buy_zone():
    """A payment / offer screen was just seen: refuse taps on the price-button area for a while."""
    global _buy_lock_until
    _buy_lock_until = time.time() + BUY_LOCK_S


def tap(p, wait=1.5):
    x0, y0, x1, y1 = BUY_ZONE
    if time.time() < _buy_lock_until and x0 <= p[0] <= x1 and y0 <= p[1] <= y1:
        log(f"BLOCKED tap {p}: payment screen seen, never buy")
        time.sleep(wait)
        return
    adb("shell", "input", "tap", str(p[0]), str(p[1]))
    time.sleep(wait)


def read(img, box):
    x0, y0, x1, y1 = box
    res = ocr(img[y0:y1, x0:x1])[0] or []
    return [(sum(p[0] for p in b) / 4 + x0, t) for b, t, _ in res]


def num(t):
    d = re.sub(r"[^\d]", "", t)
    return int(d) if d else None


def coins(img):
    """Coin counter. Tolerates icons/stars glued to the digits ("*214,600") and picks the biggest number."""
    best = None
    for _, t in read(img, COIN_BOX):
        m = re.search(r"\d[\d,\.]*\d|\d", t.strip())
        if m:
            v = num(m.group(0))
            if v is not None and (best is None or v > best):
                best = v
    return best


free_mode = False


def roll_busy(img):
    """The dice are rolling: the ROLL button is dark red (disabled) while the HUD on top is not dimmed
    (a popup would dim both). Measured 0.73 dark-red / 0.28 light-blue in the roll animation; 0.0-0.3 / 0.0 under popups."""
    c = img[1827:2127, 388:688].astype(int)
    b, g, r = c[..., 0], c[..., 1], c[..., 2]
    dark = ((r > 90) & (r < 190) & (g < 70) & (b < 70)).mean()
    top = cv2.cvtColor(img[150:240, 200:500], cv2.COLOR_BGR2HSV)
    # the lobby's own energy bar must be there too (blue strip at the bottom): the attack / kingdom pages have dark
    # maroon trees and a light-blue name banner that fooled the two tests above
    row = img[2200, 300:800].astype(int)
    bar = float(((row[:, 0] > 120) & (row[:, 2] < 150) & (row[:, 0] - row[:, 2] > 40)).mean())
    return dark > 0.5 and cv2.inRange(top, (95, 40, 190), (112, 200, 255)).mean() / 255 > 0.15 and bar > 0.5


def roll_visible(img):
    """The real lobby ROLL button is up: bright orange-red disc WITH the white dice on it (measured 0.56 red /
    0.51 white on every lobby screen; event pages whose red wooden frame covers the button give 0.18 / 0.0).
    FREE mode has its own look: trust the energy text there."""
    if free_mode:
        return True
    x0, y0, x1, y1 = ROLL_BOX
    c = img[y0 - 3:y1 + 27, x0 - 12:x1 + 8].astype(int)
    b, g, r = c[..., 0], c[..., 1], c[..., 2]
    red = ((r > 200) & (g < 130) & (b < 110) & (r > 1.8 * g)).mean()
    mid = img[1900:2040, 470:610]
    white = (mid.min(axis=2) > 225).mean()
    return red > 0.35 and white > 0.3


_E = {"val": None, "drain": 0.0, "n": 0}   # last OCR'd energy, drain per roll, rolls since that read


def energy_est(img, last_was_roll):
    """Energy for the roll loop without an OCR pass (0.35 s) on every roll: re-read every 4th roll, and on
    every roll once the estimate drops under 13 (that is where exactness matters). `drain` is how much one
    roll really took last time: 0 while extra rolls are being used up (the number stays at 50)."""
    if last_was_roll and _E["val"] is not None and _E["n"] < 3 and roll_visible(img):
        est = _E["val"] - _E["drain"] * (_E["n"] + 1)     # n+1 rolls were made since the last read
        if est > 12:
            _E["n"] += 1
            return int(round(est))
    v = energy(img)
    if v is not None:
        if _E["val"] is not None and last_was_roll:
            _E["drain"] = max(0.0, (_E["val"] - v) / (_E["n"] + 1))
        _E["val"], _E["n"] = v, 0
    else:
        _E["val"] = None
    return v


def bar_fill(img, max_e=50):
    """Energy from the bar itself (light-blue fill along the top and bottom edge of the bar, clear of the digits):
    ~0.95 at 50, 0.0 at 0. The bolt icon next to a one-digit number is read as a "4" ("49/50" for 9, "40/50" for 0),
    so the picture decides between the two readings."""
    vals = []
    for y in (2178, 2224):
        row = img[y, 300:800].astype(int)
        vals.append(float(((row[:, 0] > 180) & (row[:, 1] > 150)).mean()))
    return min(vals) / 0.95 * max_e


def _fix_by_bar(img, n, max_e=50):
    top = cv2.cvtColor(img[150:240, 200:500], cv2.COLOR_BGR2HSV)
    if cv2.inRange(top, (95, 40, 190), (112, 200, 255)).mean() / 255 < 0.15:  # HUD dimmed: the bar says nothing
        return n
    est = bar_fill(img, max_e)
    cands = [n] + ([n - 40] if 40 <= n <= 49 else []) + ([n + 40] if n <= 9 else [])
    best = min(cands, key=lambda c: abs(c - est))
    return best if abs(best - est) <= 14 else n


def energy(img):
    """Dice pool = energy N (from "N/50") + the "+M extra" rolls under the bar. One roll of xN takes N from this
    pool (the extras go first: the N/50 number stays put while they last). None when the bar is not readable."""
    global free_mode
    free_mode = False
    n = extra = None
    max_e = 50
    for _, t in read(img, ENERGY_BOX):
        m = re.search(r"(\d+)\s*/\s*(\d{2,3})", t)
        if m and n is None:
            n = int(m.group(1))
            max_e = int(m.group(2))   # the cap grows with the kingdom (50, 60, ...)
            if n > max_e:  # misread (e.g. "4" + "/50")
                n = int(str(n)[-1])
            continue
        m = re.search(r"\+?\s*(\d[\d,]*)\s*extra", t, re.I)
        if m:
            extra = int(m.group(1).replace(",", ""))
            continue
        if re.search(r"remaining", t, re.I):  # FREE roll mode; digit may misread
            free_mode = True
            d = re.sub(r"[^\d]", "", t.replace("I", "1").replace("l", "1"))
            return int(d) if d else 1
    if n is None:
        return None
    n = _fix_by_bar(img, n, max_e)
    return n + (extra or 0)


PIN_TPL = cvio.imread(os.path.join(BASE_DIR, "pin_tpl.png"))  # the blue disc + red crosshair of an attack pin


def find_pins(img, thr=0.62):
    """Attack-target pins as [(x, y)] top to bottom, found by template matching (0.97+ on a real pin,
    nothing on other screens). Pins sit on different spots in every kingdom."""
    if PIN_TPL is None:
        return []
    h = PIN_TPL.shape[0] // 2
    r = cv2.matchTemplate(img[380:1700], PIN_TPL, cv2.TM_CCOEFF_NORMED)
    out = []
    while True:
        _, mx, _, loc = cv2.minMaxLoc(r)
        if mx < thr:
            break
        out.append((loc[0] + h, loc[1] + h + 380))
        x, y = loc
        r[max(0, y - 90):y + 90, max(0, x - 90):x + 90] = 0
    return sorted(out, key=lambda p: p[1])


def _x_shaped(img, cx, cy, rad, x_min):
    """The white mark inside the round button is an X: pixels lie on the two diagonals, not on the middle cross."""
    r = int(rad * 0.55)
    c = img[max(0, cy - r):cy + r, max(0, cx - r):cx + r]
    if c.size == 0:
        return False
    m = cv2.resize((c.min(axis=2) > x_min).astype(np.uint8), (21, 21), interpolation=cv2.INTER_AREA)
    yy, xx = np.mgrid[0:21, 0:21]
    diag = (abs(xx - yy) <= 2) | (abs(xx + yy - 20) <= 2)
    cross = ((abs(xx - 10) <= 1) | (abs(yy - 10) <= 1)) & ~diag
    return bool(m[diag].mean() > 0.4 and m[diag].mean() > 1.8 * m[cross].mean())


def steal_tiles(img):
    """The glowing blue stepping tiles of the "Pick your next step and STEAL" game (5, then 4, 3, 2 as rounds
    pass): [(x, y)] left to right. The tiles sit edge to edge with no gap, so a loose brightness threshold
    fuses them into one blob; v>=240 keeps only their bright glow, which stays separate."""
    h = cv2.cvtColor(img[1600:1830], cv2.COLOR_BGR2HSV)
    m = cv2.morphologyEx(cv2.inRange(h, (85, 100, 240), (115, 255, 255)), cv2.MORPH_CLOSE, np.ones((9, 9), np.uint8))
    n, _, st, cent = cv2.connectedComponentsWithStats(m)
    tiles = [(int(cent[i][0]), int(cent[i][1]) + 1600) for i in range(1, n) if 12000 < st[i, 4] < 32000]
    return sorted(tiles) if len(tiles) >= 2 else []


def is_sling(img):
    """The slingshot screen: the maroon strap AND no popup on top (an event popup with dark bags also looks like a
    strap to the colour test, but it has a close X)."""
    return sling.sling_visible(img) and find_close_x(img) is None


def find_close_x(img):
    """Red round close button (white X) in the upper right of a popup; OCR cannot read it.
    Also the dimmed version (dark maroon disc, grey X) that shows when another popup sits on top.
    Returns the centre (x, y) or None."""
    x0, y0, x1, y1 = 650, 120, 1080, 900
    c = img[y0:y1, x0:x1].astype(int)
    b, g, r = c[..., 0], c[..., 1], c[..., 2]
    bright = ((r > 190) & (g < 90) & (b < 130)).astype(np.uint8) * 255
    dim = ((r > 40) & (r < 130) & (r - g > 25) & (r - b > 10) & (g < 60)).astype(np.uint8) * 255
    for mask, x_min in ((bright, 200), (dim, 55)):
        mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, np.ones((5, 5), np.uint8))
        cnts, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        best = None
        for cnt in cnts:
            area = cv2.contourArea(cnt)
            if not 2500 < area < 12000:
                continue
            (cx, cy), rad = cv2.minEnclosingCircle(cnt)
            if area / (np.pi * rad * rad) < 0.6:  # roughly round
                continue
            # a close button has an X inside: bright (or, dimmed, light-grey) pixels near its centre
            inner = img[int(y0 + cy - rad * 0.5):int(y0 + cy + rad * 0.5),
                        int(x0 + cx - rad * 0.5):int(x0 + cx + rad * 0.5)]
            if inner.size == 0 or (inner.min(axis=2) > x_min).mean() < 0.08:
                continue
            if not _x_shaped(img, int(x0 + cx), int(y0 + cy), rad, x_min):
                continue  # white digits on a red notification badge ("400") are not a close button
            if best is None or area > best[2]:
                best = (int(x0 + cx), int(y0 + cy), area)
        if best:
            return best[:2]
    return None


def multiplier(img=None):
    """Read the xN badge next to ROLL (upscaled, retried: the badge animates after a tap)."""
    for attempt in range(4):
        if img is None or attempt:
            time.sleep(0.4)
            img = shot()
        n = read_badge_num(img)
        if n is not None:
            return n
    return None


def read_badge_num(img):
    """OCR the xN badge once (no retry) for its exact number; None if unreadable (e.g. mid-animation)."""
    x0, y0, x1, y1 = MULT_BOX
    crop = cv2.resize(img[y0:y1, x0:x1], None, fx=3, fy=3, interpolation=cv2.INTER_CUBIC)
    for r in ocr(crop)[0] or []:
        m = re.search(r"[xX×]\s*(\d+)", r[1])
        if m:
            return int(m.group(1))
    return None


def read_max_mult(img):
    """OCR the 'MAX xN' bubble above the badge: the highest multiplier on offer right now (can exceed the
    old x1/x2/x3/x5/x8 cycle, e.g. x10), or None when the bubble isn't shown."""
    x0, y0, x1, y1 = MAX_BOX
    crop = cv2.resize(img[y0:y1, x0:x1], None, fx=3, fy=3, interpolation=cv2.INTER_CUBIC)
    for r in ocr(crop)[0] or []:
        m = re.search(r"[xX×]\s*(\d+)", r[1])
        if m:
            return int(m.group(1))
    return None


def badge_color(img):
    """Mean BGR of the xN badge's fill (blue=x2, green=x3, ...); OCR cannot read the white text."""
    x, y = MULT_BTN
    return img[y - 30:y + 30, x - 45:x + 45].reshape(-1, 3).mean(axis=0)


def same_color(a, b):
    return np.abs(a - b).max() < 35


def set_max_multiplier():
    """Press xN around the full cycle; the step just before the colour repeats is the
    highest (the cycle wraps back to x1). Then press forward until we are on it."""
    colors = [badge_color(shot())]
    for _ in range(10):
        tap(MULT_BTN, 1.0)
        c = badge_color(shot())
        if same_color(c, colors[0]):
            break
        colors.append(c)
    n = len(colors)
    # x1 is the silver badge (lowest saturation); the step right before it is the highest
    sat = [cv2.cvtColor(np.uint8([[c]]), cv2.COLOR_BGR2HSV)[0, 0, 1] for c in colors]
    lowest = int(np.argmin(sat))
    top = (lowest - 1) % n
    for _ in range(top):  # we are back on colors[0]; press forward to the top step
        tap(MULT_BTN, 1.0)
    log(f"multiplier cycle {n} steps (sat {sat}), moved to step {top + 1}/{n}")


FIRE_LEAD = 0.15   # earliest release after the last capture (s)
ADB_DELAY = 0.05   # `adb shell input motionevent` delivery delay (s)
STEPS = [1, 2, 3]  # xN steps the button currently cycles through; re-measured, x5 only shows up sometimes
_steps_checked = 0.0


def best_step(energy):
    """Largest available xN whose cost (= N energy) we can still pay: spends the energy down to 0."""
    ok = [s for s in STEPS if s <= max(1, energy)]
    return max(ok) if ok else min(STEPS)


def discover_steps():
    """Press the xN button once around and note every step it shows (x5 appears with full energy)."""
    global STEPS, _steps_checked
    if time.time() < _buy_lock_until:  # a payment screen was just seen: taps are blocked, measure later
        return STEPS
    seen = []
    for _ in range(8):
        img = shot()
        if not roll_visible(img) or find_close_x(img) is not None:
            return STEPS
        s = badge_value(img)
        if s is None:
            return STEPS
        if s in seen:
            break
        seen.append(s)
        tap(MULT_BTN, 0.9)
    if seen:
        STEPS = sorted(set(seen) | {1, 2, 3})  # x1..x3 always exist; x5/x8/x10 are the optional extras
    _steps_checked = time.time()
    log(f"multiplier steps available: {STEPS}")
    return STEPS


def forget_steps():
    global _steps_checked
    _steps_checked = 0.0


def badge_step(img):
    """Which xN the badge shows, from its colour: orange=x5, silver=x1, blue=x2, green=x3.
    Red (h<=7 or h>=170) covers both x8 and x10 -> returns 8 as a guess; use badge_value() when the
    distinction matters."""
    h, s, v = cv2.cvtColor(np.uint8([[badge_color(img)]]), cv2.COLOR_BGR2HSV)[0, 0]
    if v < 120:  # dimmed by a popup / overlay: cannot tell
        return None
    if h <= 7 or h >= 170:
        return 8  # red (x8 or x10 - ambiguous by colour alone)
    if h < 30:
        return 5  # orange
    if s < 80:
        return 1
    return 3 if h < 85 else 2


def badge_value(img):
    """Current xN: OCR'd number when readable (accurate even for x8 vs x10), else the colour guess."""
    n = read_badge_num(img)
    return n if n is not None else badge_step(img)


def set_multiplier(target):
    """Make the badge show `target`. The button cycles x1 -> x2 -> x3 -> (x5) -> x8 -> x1, so from the colour of the
    badge we know how many presses it takes: press them all, then check once. (Falls back to one press at a
    time.) Only taps while the plain board is visible, never on top of a popup. True when it shows `target`."""
    img = shot()
    if not roll_visible(img) or find_close_x(img) is not None:
        return False
    cur = badge_value(img)
    if cur == target:
        return True
    if cur in STEPS and target in STEPS:
        presses = (STEPS.index(target) - STEPS.index(cur)) % len(STEPS)
        for _ in range(presses):
            tap(MULT_BTN, 0.45)
        time.sleep(0.3)
        img = shot()
        if roll_visible(img) and badge_value(img) == target:
            return True
    for _ in range(len(STEPS) + 2):  # fallback: one press at a time, looking after each
        img = shot()
        if not roll_visible(img) or find_close_x(img) is not None:
            return False
        if badge_value(img) == target:
            return True
        tap(MULT_BTN, 0.7)
    img = shot()
    return roll_visible(img) and badge_value(img) == target


def parse_price(t):
    """'17,500' -> 17500, '104K' -> 104000, '1.2M' -> 1200000, '2.5B' -> 2500000000 (big prices are abbreviated)."""
    t = t.strip().replace(" ", "")
    if re.fullmatch(r"\d{1,3}(,\d{3})+", t):
        return num(t)
    m = re.fullmatch(r"(\d{1,3}(?:[.,]\d{1,3})?)([KkMmBbGg])", t)
    if m:
        v = float(m.group(1).replace(",", "."))
        return int(round(v * {"k": 1e3, "m": 1e6, "b": 1e9, "g": 1e9}[m.group(2).lower()]))
    return None


def prices(img):
    """[(price, x)] of the green price buttons, left to right (the strip's order = the build order)."""
    out = []
    for x, t in read(img, PRICE_BOX):
        p = parse_price(t)
        if p:
            out.append((p, int(x)))
    return sorted(out, key=lambda a: a[1])


LOG_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "logs")


def log(*a):
    """Print to the screen and append to logs/YYYY-MM-DD.log (one file per day, kept across restarts)."""
    line = time.strftime("%H:%M:%S") + " " + " ".join(str(x) for x in a)
    print(line, flush=True)
    try:
        os.makedirs(LOG_DIR, exist_ok=True)
        with open(os.path.join(LOG_DIR, time.strftime("%Y-%m-%d") + ".log"), "a", encoding="utf-8") as fh:
            fh.write(line + chr(10))
    except OSError:
        pass


CROWN_Y = 2053                       # crown row of every building card
CROWN_DX = (-127, -65, -1, 61)       # the 4 crowns, relative to the card centre (5th slot = gift)
PRICE_TO_CENTER = -29                # card centre x = price-text x + this


def scroll_cards(direction, px=650):
    """Swipe the card strip: direction +1 shows cards further right, -1 goes back left."""
    a, b = (950, 950 - px) if direction > 0 else (150, 150 + px)
    adb("shell", "input", "swipe", str(a), "2050", str(b), "2050", "450")  # a slower swipe throws the strip less
    time.sleep(0.3)


def settle(max_s=2.5):
    """Wait until the card strip stands still (two frames in a row alike) and return that frame: a scroll keeps
    gliding for a moment and prices read on a moving strip come out wrong or double."""
    prev, img, t0 = None, None, time.time()
    while time.time() - t0 < max_s:
        img = shot()
        key = img[1960:2260:6, ::6].astype(int)
        if prev is not None and float(np.abs(key - prev).mean()) < 2.0:
            return img
        prev = key
    return img


def read_page():
    """One screen of the strip (three cards): wait for it to settle, read the prices, and read once more when the
    list differs from a second look. Returns (frame, [(price, x), ...] left to right)."""
    img = settle()
    ps = prices(img)
    if ps:
        img2 = shot()
        ps2 = prices(img2)
        if [p for p, _ in ps2] != [p for p, _ in ps]:
            img, ps = img2, ps2
    return img, ps


def strip_sig(img):
    return img[1960:2260:6, ::6].astype(np.int16)


def strip_same(a, b, thr=2.0):
    return float(np.abs(a - b).mean()) < thr


def scroll_to_start():
    """Swipe the strip back to its first card, stopping as soon as a swipe changes nothing (the strip is at its
    left end): usually one swipe when it already was there, instead of a fixed number of blind ones.
    Returns the frame of the start page."""
    prev = strip_sig(shot())
    img = None
    for _ in range(6):
        scroll_cards(-1, 800)
        img = shot()
        cur = strip_sig(img)
        if strip_same(prev, cur):
            return img
        prev = cur
    return img


def crowns_filled(img, price_x):
    """How many of the 4 crown slots of the card are gold (0..4); a 5th buy completes the building."""
    cx = price_x + PRICE_TO_CENTER
    hsv = cv2.cvtColor(img[CROWN_Y - 14:CROWN_Y + 14], cv2.COLOR_BGR2HSV)
    n = 0
    for dx in CROWN_DX:
        x = cx + dx
        if x < 12 or x > img.shape[1] - 12:
            continue  # slot is off-screen: unknown, treated as not filled
        h, s, v = np.median(hsv[:, x - 10:x + 10].reshape(-1, 3), axis=0)
        if 12 <= h <= 38 and s > 110 and v > 170:
            n += 1
    return n


def scan_cards():
    """Walk the whole strip once; returns a list of dicts (price, crowns, page) for every card."""
    img = scroll_to_start()
    seen = {}
    for page in range(8):
        ps = prices(img)
        for price, x in ps:
            seen.setdefault(price, {"price": price, "crowns": crowns_filled(img, x), "page": page})
        before = strip_sig(img)
        scroll_cards(+1, 900)  # one page = the three visible cards
        img = shot()
        if strip_same(before, strip_sig(img)):
            img = shot()  # still gliding? look once more before calling it the end
            if strip_same(before, strip_sig(img)):
                break  # the swipe changed nothing: that was the end of the strip
    return list(seen.values())


def go_to_card(card, coins_now):
    """Scroll to the card and tap its price button if affordable. Returns True when tapped."""
    scroll_to_start()
    for _ in range(card["page"]):
        scroll_cards(+1)
    img = shot()
    for price, x in prices(img):
        if price == card["price"]:
            if price > coins_now:
                return False
            tap((x, BUTTON_Y), 2.5)
            return True
    return False


VID_TPL = cvio.imread(os.path.join(BASE_DIR, "vid_tpl84.png"))  # the purple clapper + dice bubble: "watch a video for dice"
GAME_PKG = "com.superplaystudios.dicedreams"
_last_ad = 0.0
_ads_in_batch = 0       # videos watched in the current refill (reset when a new refill starts; just for logging)
_ads_resume = 0.0       # (kept for the one-hour stall fallback)


VID_TPL_B = cvio.imread(os.path.join(BASE_DIR, "vid_tpl_b.png"))   # the same bubble on a pale background (desert kingdom)


def find_video_bubble(img, thr=0.62):
    """Centre of the free-video bubble above the character in the lobby, or None (0.7 real / <=0.45 elsewhere)."""
    best = None
    for tpl in (VID_TPL, VID_TPL_B):
        if tpl is None:
            continue
        r = cv2.matchTemplate(img[300:1700], tpl, cv2.TM_CCOEFF_NORMED)
        _, mx, _, loc = cv2.minMaxLoc(r)
        if mx >= thr and (best is None or mx > best[0]):
            h = tpl.shape[0] // 2
            best = (mx, loc[0] + h, loc[1] + h + 300)
    return best[1:] if best else None


LOCK_TPLS = [t for t in (
    cvio.imread(os.path.join(BASE_DIR, "lock_tpl.png")),    # gold padlock+chain (milestone grid / VIDEO CRAZE)
    cvio.imread(os.path.join(BASE_DIR, "lock_tpl2.png")),   # plain corner padlock, no chain (paid OFFER tiles)
) if t is not None]
LOCK_SCALES = (0.6, 0.8, 1.0, 1.2, 1.5)
LOCK_THR = 0.69  # measured across both templates/layouts: locked tiles score >=0.73, unlocked <=0.67


def watch_locked(img, x, y):
    """A reward-path tile's button sits near a gold padlock icon when that tile is locked (milestone grids,
    VIDEO CRAZE, and paid OFFER ladders all use this, in a couple of different icon styles and positions - a
    chain hanging below the button, or a plain corner padlock well above it). Search a generous area around
    the button at any scale, since the lock sits in a different spot in each layout; a plain gold tile border
    never matches either template."""
    if not LOCK_TPLS:
        return False
    y0, y1 = max(0, y - 420), min(img.shape[0], y + 220)
    x0, x1 = max(0, x - 300), min(img.shape[1], x + 300)
    region = img[y0:y1, x0:x1]
    for tpl in LOCK_TPLS:
        for s in LOCK_SCALES:
            t = cv2.resize(tpl, None, fx=s, fy=s, interpolation=cv2.INTER_AREA if s < 1 else cv2.INTER_LINEAR)
            if t.shape[0] >= region.shape[0] or t.shape[1] >= region.shape[1]:
                continue
            if cv2.matchTemplate(region, t, cv2.TM_CCOEFF_NORMED).max() >= LOCK_THR:
                return True
    return False


BACK_ARROW = cvio.imread(os.path.join(BASE_DIR, "backarrow_mask.png"), 0)  # light-blue "<-" of full-screen event pages


def find_back_arrow(img, thr=0.7):
    """Centre of the light-blue back arrow in the top-left corner (event pages / mini-games), or None."""
    if BACK_ARROW is None:
        return None
    m = cv2.inRange(cv2.cvtColor(img[90:400, 0:260], cv2.COLOR_BGR2HSV), (88, 40, 225), (110, 170, 255))
    r = cv2.matchTemplate(m, BACK_ARROW, cv2.TM_CCOEFF_NORMED)
    _, mx, _, loc = cv2.minMaxLoc(r)
    if mx < thr:
        return None
    x, y = loc[0] + BACK_ARROW.shape[1] // 2, loc[1] + BACK_ARROW.shape[0] // 2 + 90
    return (x, y) if x < 150 else None  # the lobby's light-blue coin pill (x~200) looks a bit like an arrow


def focus():
    """Name of the window that has focus ('' if unknown)."""
    out = subprocess.run([ADB, "shell", "dumpsys window | grep mCurrentFocus"], capture_output=True, text=True).stdout
    return out.strip()


AD_WORDS = ("fullscreen", "adrenderer", ".ads.", "adactivity", "applovin", "bytedance", "openadsdk", "adview",
            "mbridge", "mintegral", "vungle", "ironsource", "admob", "chartboost", "inmobi", "pangle", "videoactivity",
            "rewarded", "interstitial")


PROTECTED_PKGS = ("android", "com.android.systemui", "com.sec.android.app.launcher", "com.samsung.android.app.launcher",
                  GAME_PKG if "GAME_PKG" in globals() else "com.superplaystudios.dicedreams")


def leave_other_app(f):
    """Another app opened over the game (Play Store, a browser, an advertiser's app such as Trip.com).
    Stores and browsers are killed at once (BACK just loops inside them). Any other app gets one BACK; if it is
    still in front after that (some apps want BACK twice or ignore it) it is force-stopped, and the game is
    brought back if needed. Nothing is ever installed or bought."""
    for pkg in ("com.android.vending", "com.android.chrome", "com.sec.android.app.sbrowser"):
        if pkg in f:
            adb("shell", "am", "force-stop", pkg)
            time.sleep(1.5)
            return
    m = re.search(r"\s([\w.]+)/", f)
    pkg = m.group(1) if m else ""
    adb("shell", "input", "keyevent", "KEYCODE_BACK")
    time.sleep(1.2)
    f2 = focus()
    if pkg and pkg in f2 and pkg not in PROTECTED_PKGS:
        log(f"{pkg} is still in front after BACK: closing the app")
        adb("shell", "am", "force-stop", pkg)
        time.sleep(1.5)
        if GAME_PKG not in focus():
            adb("shell", "monkey", "-p", GAME_PKG, "-c", "android.intent.category.LAUNCHER", "1")
            time.sleep(4)
    else:
        time.sleep(0.8)


STUCK_S = 150        # seconds without seeing the lobby (and no video playing) before the recovery ladder starts
_last_ok = time.time()
_recover_n = 0


def touch_ok():
    """Something useful happened (lobby seen, ad finished, ...): restart the stuck timer."""
    global _last_ok, _recover_n
    _last_ok, _recover_n = time.time(), 0


def recover(img, stuck):
    """Stuck on one page for too long (new ad / event / card nobody taught the bot): press whatever could lead out,
    escalating - known exits, text buttons, other bright corner glyphs, BACK, closing the foreground app,
    finally restarting the game - until the lobby is back. Payment-looking pages only get X / BACK."""
    global _recover_n
    _recover_n += 1
    n = _recover_n
    log(f"stuck for {stuck:.0f}s without the lobby: recovery step {n}")
    f = focus()
    if f and GAME_PKG not in f and not is_ad_any(f):
        leave_other_app(f)
        return
    found = ocr(img)[0] or []
    texts = " ".join(r[1] for r in found).upper()
    pay = bool(re.search(r"[$₩€£]|W\s?\d|\d\s*원|UNLOCK|GOOGLE PLAY", texts))
    # 1. exits we recognise
    for xy in (find_close_x(img), adlearn.find_dialog_x(img), find_back_arrow(img), find_skip_text(img)):
        if xy:
            log(f"recovery: pressing the exit at {xy}")
            tap(xy, 1.5)
            return
    hit = adlearn.find_known(img)
    if hit and not adlearn.is_bad(img, hit[0], hit[1]):
        log(f"recovery: pressing the known exit glyph {hit[2]} at {hit[:2]}")
        tap(hit[:2], 1.5)
        return
    for b, t, _ in found:
        tok = t.strip().upper().strip("!")
        if tok in BUTTONS and not (tok == "FREE" and pay):
            xy = (int(sum(q[0] for q in b) / 4), int(sum(q[1] for q in b) / 4))
            log(f"recovery: pressing '{t}' at {xy}")
            tap(xy, 1.5)
            return
    # 2. escalate with time
    if stuck < 240:
        cands = adlearn.candidates(img)
        if cands and not pay and n % 2 == 1:
            c = cands[(n // 2) % len(cands)]
            log(f"recovery: trying the corner glyph at {c[:2]}")
            tap(c[:2], 1.5)
        elif n % 3 == 0 or pay:
            log("recovery: BACK")
            adb("shell", "input", "keyevent", "KEYCODE_BACK")
            time.sleep(1.2)
        else:
            tap(UNKNOWN_TAPS[n % len(UNKNOWN_TAPS)], 1.2)
    elif stuck < 330:
        log("recovery: BACK twice")
        for _ in range(2):
            adb("shell", "input", "keyevent", "KEYCODE_BACK")
            time.sleep(1.2)
    else:
        log("recovery: nothing worked - restarting the game")
        adb("shell", "am", "force-stop", GAME_PKG)
        time.sleep(2)
        adb("shell", "monkey", "-p", GAME_PKG, "-c", "android.intent.category.LAUNCHER", "1")
        time.sleep(25)
        touch_ok()


TRAIL_ICON = (953, 1977)             # lobby, bottom right: the TRAIL event icon (its badge = trail tokens)
TRAIL_BADGE = (950, 1880, 1060, 1935)   # the token count on that icon
TRAIL_GO = (538, 1895)               # trail screen: the big GO! button
TRAIL_MULT = (805, 1895)             # trail screen: the xN badge (each tap = next multiplier)
TRAIL_TOKENS_BOX = (330, 2090, 780, 2200)
TRAIL_MULT_BOX = (730, 1840, 900, 1960)
TRAIL_CYCLE = [1, 5, 10, 15, 20, 30, 50, 100, 200, 400, 600, 800, 1200, 2000]   # measured: one tap = next entry
TRAIL_AT = 200        # start spending when this many tokens have piled up ...
TRAIL_BEST = 50       # ... at x50 (as the user asked), stepping down for the remainder until 0
_trail_check = 0.0


def _num_from(img, box, scale=2):
    x0, y0, x1, y1 = box
    c = cv2.resize(img[y0:y1, x0:x1], None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC)
    best = None
    for _, t, _ in ocr(c)[0] or []:
        d = re.sub(r"[^\d]", "", t)
        if d and (best is None or len(d) > len(best)):
            best = d
    return int(best) if best else None


def trail_tokens_lobby(img):
    return _num_from(img, TRAIL_BADGE, 3)


def hammer_badge(img):
    """The hammer icon's red badge: how many upgrade steps are affordable right now, or None when it isn't
    shown (nothing affordable)."""
    return _num_from(img, HAMMER_BADGE, 3)


def trail_tokens_screen(img):
    return _num_from(img, TRAIL_TOKENS_BOX, 2)


def trail_mult(img):
    x0, y0, x1, y1 = TRAIL_MULT_BOX
    c = cv2.resize(img[y0:y1, x0:x1], None, fx=3, fy=3, interpolation=cv2.INTER_CUBIC)
    for _, t, _ in ocr(c)[0] or []:
        m = re.fullmatch(r"[xX×]\s*(\d{1,4})", t.strip())
        if m and int(m.group(1)) in TRAIL_CYCLE:
            return int(m.group(1))
    return None


def trail_screen(img):
    """On the trail page: the GO button (orange disc) in the middle bottom and the wheel above it."""
    c = img[1790:2000, 400:680].astype(int)
    b, g, r = c[..., 0], c[..., 1], c[..., 2]
    return float(((r > 200) & (g < 130) & (b < 90)).mean()) > 0.2 and trail_tokens_screen(img) is not None


def trail_set_mult(target):
    """Tap the xN badge until it reads `target` (the cycle is known, so count the taps)."""
    for _ in range(3):
        cur = trail_mult(shot())
        if cur == target:
            return True
        if cur in TRAIL_CYCLE:
            n = (TRAIL_CYCLE.index(target) - TRAIL_CYCLE.index(cur)) % len(TRAIL_CYCLE)
        else:
            n = 1
        for _ in range(n):
            tap(TRAIL_MULT, 0.5)
        time.sleep(0.6)
    return trail_mult(shot()) == target


def use_trail():
    """Spend the trail tokens down to 0: x50 spins while at least 50 remain, then the biggest multiplier that fits
    (30, 20, 15, 10, 5, 1) for the rest. Each spin: GO, wait, take whatever pops up (chest, TAP, COLLECT, X)."""
    log("trail: opening the TRAIL event")
    if not trail_screen(shot()):
        tap(TRAIL_ICON, 3.5)
    for _ in range(8):
        if trail_screen(shot()):
            break
        time.sleep(1.0)
    else:
        log("trail: the page did not open")
        return False
    spins, bad, last, mult_fail, t_start = 0, 0, None, 0, time.time()
    for _ in range(60):
        img = shot()
        if not trail_screen(img):
            # a chest / card / reward popup is on top: take it (X, a named button, or a tap anywhere)
            xy = find_close_x(img)
            if xy:
                tap(xy, 1.2)
                continue
            found = ocr(img)[0] or []
            hit = next(((int(sum(q[0] for q in b) / 4), int(sum(q[1] for q in b) / 4)) for b, t, _ in found
                        if t.strip().upper().strip("!") in BUTTONS), None)
            if roll_visible(img):
                log("trail: back in the lobby")
                break
            tap(hit or ANYWHERE, 1.0)
            continue
        tokens = trail_tokens_screen(img)
        if tokens is None or tokens < 1:
            log("trail: no tokens left")
            break
        want = max([m for m in TRAIL_CYCLE if m <= min(TRAIL_BEST, tokens)] or [1])
        if trail_mult(img) != want and not trail_set_mult(want):
            mult_fail += 1
            log(f"trail: could not set x{want} ({mult_fail}/3)")
            if mult_fail >= 3:
                break
            time.sleep(2.0)  # a reward popup may be sliding in: look again
            continue
        mult_fail = 0
        if spins >= 40 or time.time() - t_start > 900:
            log("trail: spin / time limit reached, leaving")
            break
        spins += 1
        log(f"trail: spin #{spins} at x{want} (tokens {tokens})")
        tap(TRAIL_GO, 1.0)
        t0 = time.time()
        changed = False
        while time.time() - t0 < 25:   # the spin, the walk and any chest take a while: wait for the count to move
            time.sleep(1.0)
            im2 = shot()
            if trail_screen(im2):
                n2 = trail_tokens_screen(im2)
                if n2 is not None and n2 != tokens:
                    changed = True
                    break
            else:
                xy = find_close_x(im2)
                found = ocr(im2)[0] or []
                hit = next(((int(sum(q[0] for q in b) / 4), int(sum(q[1] for q in b) / 4)) for b, t, _ in found
                            if t.strip().upper().strip("!") in BUTTONS), None)
                tap(xy or hit or ANYWHERE, 0.8)
        bad = 0 if changed else bad + 1
        if changed:
            time.sleep(2.5)  # the walk / chest after a spin: GO does not react until it is over
        if bad >= 3:
            log("trail: the count does not move, leaving")
            break
    log(f"trail: done after {spins} spins")
    for _ in range(3):  # back to the lobby
        img = shot()
        if roll_visible(img):
            break
        ba = find_back_arrow(img)
        tap(ba or (105, 210), 2.0)
    return True


def maybe_trail(img):
    """Lobby check, at most every 2 minutes: TRAIL badge >= TRAIL_AT -> spend them."""
    global _trail_check
    if time.time() - _trail_check < 120:
        return False
    _trail_check = time.time()
    n = trail_tokens_lobby(img)
    if n is not None and n >= TRAIL_AT:
        log(f"trail tokens {n} >= {TRAIL_AT}: spending them")
        return use_trail()
    return False


def video_craze_screen(img):
    """True on the VIDEO CRAZE event page (its own popup: a vertical list of WATCH tiers, each unlocking the
    next), found by its title in the top band."""
    texts = "".join(t for _, t, _ in ocr(img[150:700])[0] or []).upper().replace(" ", "")
    return "CRAZE" in texts


def paid_offer_screen(img):
    """A real-money purchase funnel ('... OFFER', e.g. 'ROYAL ARMOR OFFER'): a ladder of tiles, some genuinely
    FREE (no padlock) and some chained behind a paid tile (locked until that one is bought). Never buy
    anything here - claim what's actually free, then leave once none are left."""
    texts = " ".join(t for _, t, _ in ocr(img[150:500])[0] or []).upper()
    return bool(re.search(r"\bOFFER\b", texts)) and "CRAZE" not in texts


def use_paid_offer():
    """On a paid '... OFFER' ladder: claim every FREE tile that isn't locked (the padlock+chain means it sits
    behind a paid one), then close - once none are unlocked, the rest all need a real purchase first, which
    this bot never does."""
    claimed = 0
    for _ in range(8):
        img = shot()
        if not paid_offer_screen(img):
            break
        found = ocr(img)[0] or []
        wt = [(int(sum(p[0] for p in b) / 4), int(sum(p[1] for p in b) / 4)) for b, t, _ in found
              if t.strip().upper() == "FREE"]
        wt = [p for p in wt if not watch_locked(img, *p)]
        if not wt:
            break
        log(f"paid offer: claiming free tile #{claimed + 1} at {wt[0]}")
        tap(wt[0], 1.5)
        claimed += 1
    log(f"paid offer: claimed {claimed} free tile(s), closing")
    img = shot()
    xy = find_close_x(img)
    if xy:
        tap(xy, 1.5)
    elif paid_offer_screen(img):
        adb("shell", "input", "keyevent", "KEYCODE_BACK")
    return claimed


def use_video_craze():
    """Watch every unlocked tier of VIDEO CRAZE back-to-back (bypasses the regular popup-WATCH rate limit:
    this event is meant to be cleared in one go, each watch unlocking the next tier down)."""
    watched = 0
    for _ in range(10):
        img = shot()
        if not video_craze_screen(img):
            break
        found = ocr(img)[0] or []
        wt = [(int(sum(p[0] for p in b) / 4), int(sum(p[1] for p in b) / 4)) for b, t, _ in found
              if t.strip().upper().startswith("WATCH") and len(t.strip()) <= 14]
        wt = [p for p in wt if not watch_locked(img, *p)]
        if not wt:
            break
        log(f"video craze: tier #{watched + 1} at {wt[0]}")
        tap(wt[0], 3)
        if not is_ad_focus(focus()):
            break  # the tap did nothing (e.g. daily watch limit reached): stop, don't loop forever
        watched += 1
        ride_ad()
    log(f"video craze: done, watched {watched} tier(s)")
    img = shot()
    if video_craze_screen(img):
        xy = find_close_x(img)
        if xy:
            tap(xy, 1.2)
    return watched > 0


def is_ad_any(f):
    """An ad window, also when it runs in another package (Facebook Audience Network and friends)."""
    fl = f.lower()
    return any(k in fl for k in AD_WORDS + ("audiencenetwork", "facebook.ads", "ads.internal"))


def is_ad_focus(f):
    f = f.lower()
    return GAME_PKG in f and any(k in f for k in AD_WORDS)


def find_ad_x_glyph(img):
    """Any learned exit glyph (X, >>, ▶|, ...) in a top corner -> (x, y) or None."""
    hit = adlearn.find_known(img)
    return (hit[0], hit[1]) if hit else None


def find_skip_text(img):
    """A "Skip" / "Skip Ad" / "건너뛰기" button read as text in the top band of an ad (Meta / Audience Network videos draw
    it as a pill with the word) -> centre or None. The ad network itself only shows/enables this after its own
    countdown, so finding it already means it's safe to tap (the reward is secured)."""
    for b, t, _ in ocr(img[60:330, 0:1080])[0] or []:
        tt = t.strip().upper()
        if tt.startswith("SKIP") or tt in ("건너뛰기", "광고 건너뛰기", "CLOSE", "닫기"):
            return int(sum(p[0] for p in b) / 4) + 40, int(sum(p[1] for p in b) / 4) + 60
    return None


def find_google_play_text(img):
    """A "Google Play" banner/button, read as text in the top band of an ad -> centre or None. Unlike Skip,
    this is often shown the whole time the ad plays, not gated by any countdown - only use this once
    ad_playing(img) says the video itself is done, or tapping it can cut the video short before the reward
    threshold. Tapping it leaves to the Play Store, which leave_other_app() force-stops and returns from
    (nothing is ever installed) - faster than waiting out an ad with no real skip/X on it."""
    for b, t, _ in ocr(img[60:330, 0:1080])[0] or []:
        if "GOOGLE PLAY" in t.strip().upper():
            return int(sum(p[0] for p in b) / 4) + 40, int(sum(p[1] for p in b) / 4) + 60
    return None


def find_ad_close(img):
    hit = find_ad_x_glyph(img)
    if hit:
        return hit
    return find_ad_close_box(img)


def find_ad_close_box(img):
    """The ad's close X: a white X on a dark rounded square in the top-right or top-left corner.
    Never the 'download' / 'Google Play' buttons (those open the store)."""
    for cx in (1005, 986, 75, 94):
        for cy in (107, 192):  # end cards put the X a bit lower (y~192) and further in (x~986)
            box = img[cy - 50:cy + 50, cx - 50:cx + 50]
            white = float((box.min(axis=2) > 235).mean())
            dark = float((box.mean(axis=2) < 120).mean())
            if white > 0.012 and dark > 0.6:
                return cx, cy
    return None


def watch_ad(img=None, max_s=150):
    """Start the free video from the lobby bubble, wait it out, close it with its X, and get back to the game.
    No cap here: the caller (main loop) stops asking for more as soon as any energy is back."""
    global _last_ad, _ads_in_batch
    img = shot() if img is None else img
    pos = find_video_bubble(img)
    if pos is None or find_close_x(img) is not None or not roll_visible(img):
        return False
    _last_ad = time.time()
    tap(pos, 3)
    if not is_ad_focus(focus()):  # the bubble tap did not open a video: not an ad, do not count it
        return True
    _ads_in_batch += 1
    log(f"ad: watching a free video #{_ads_in_batch} (refilling to 50 energy, bubble at {pos})")
    ride_ad()
    return True


VIDEO_BOX = (700, 200, 1080, 1050)  # lobby, right side icon stack: where the "VIDEO" bonus-ad icon can be


def try_video_event(img=None):
    """Tap the VIDEO bonus-ad icon, found by its text - the right-side icon stack reorders depending on what's
    currently active, so a fixed position can land on a different icon (e.g. a paid OFFER) once VIDEO isn't
    there at all. Only counts as a watch (pays more than the regular lobby bubble) when it's actually off
    cooldown - a tap while it's still counting down does nothing, which is how this tells the two apart."""
    global _last_ad
    img = shot() if img is None else img
    if find_close_x(img) is not None or not roll_visible(img):
        return False
    x0, y0, x1, y1 = VIDEO_BOX
    found = ocr(img[y0:y1, x0:x1])[0] or []
    hit = next(((int(sum(p[0] for p in b) / 4) + x0, int(sum(p[1] for p in b) / 4) + y0)
                for b, t, _ in found if t.strip().upper() == "VIDEO"), None)
    if hit is None:
        return False  # no VIDEO icon right now: let the caller fall back to the regular lobby bubble
    tap(hit, 2.0)
    if not is_ad_focus(focus()):  # still on cooldown: the tap did nothing
        return False
    _last_ad = time.time()
    log(f"video event: off cooldown at {hit}, watching the bonus ad")
    ride_ad()
    return True


def landing_page_bar(img):
    """A clicked-through ad landing page (opened in its own in-app browser) shows a light toolbar near the
    top (back arrow + X + title) - the opposite colours of the ad's own close buttons (dark glyphs on white,
    not a white glyph on a dark corner button), so the usual X-hunting never finds it. BACK always backs out
    of it safely (never installs or buys anything), so there is no need to locate the X itself."""
    band = img[130:180, 0:900].astype(int)
    light = float((band.min(axis=2) > 225).mean())
    dark = float((band.max(axis=2) < 90).mean())  # the '<' and 'X' glyphs themselves
    return light > 0.6 and 0.01 < dark < 0.25


def ad_playing(img):
    """Video ads draw a thin progress bar on the very bottom row: white = played, grey (168,148,148) = to go.
    True while the video has not reached its end (the bar disappears or is full when it is done)."""
    if img.shape[0] <= 2334:  # some ads rotate the screen to landscape: no portrait row to read yet
        return True  # assume still playing; re-checked every loop, so this self-corrects once it rotates back
    row = img[2334].astype(int)
    grey = (np.abs(row - np.array([168, 148, 148])).max(axis=1) < 14).mean()
    white = (row.min(axis=1) > 235).mean()
    return grey >= 0.02 and grey + white >= 0.9


def ride_ad(max_s=150):
    try:
        _ride_ad(max_s)
    finally:
        touch_ok()


def _ride_ad(max_s=150):
    """An ad is in front: close it with a known exit button, or try the corner buttons one by one and learn
    (adlearn) which of them leads out, so the next ad with that button closes at once."""
    t0 = time.time()
    poked = backed = stored = False
    tried = []          # corner buttons already pressed in this ad
    pending = None      # (screenshot before, candidate, time) of the last unknown button we pressed
    last_try = 0.0
    pressed = {}        # known button -> times pressed in this ad (a button that never works is skipped after 3)
    t_abs = time.time()
    while time.time() - t0 < max_s and time.time() - t_abs < 420:
        f = focus()
        in_game = GAME_PKG in f and not is_ad_focus(f)
        if in_game and time.time() - t0 > 6:
            if pending and time.time() - pending[2] < 4.5:
                p = adlearn.learn_exit(pending[0], pending[1])
                if p:
                    log(f"ad: learned a new exit button -> {os.path.basename(p)}")
            break  # back in the game (the video closed itself or we closed it)
        if GAME_PKG not in f and f and not is_ad_any(f):  # an ad opened the Play Store / a browser: come back, never install
            log(f"ad: left the game ({f[-60:]}), going back")
            if pending and time.time() - pending[2] < 4.5:
                p = adlearn.learn_bad(pending[0], pending[1])
                log(f"ad: that button only opened the store, remembered as useless ({p})")
                pending = None
            leave_other_app(f)
            continue
        img = shot()
        if landscape(img):
            # a rotated ad: every *fixed* portrait coordinate below would tap the wrong spot, so only act on
            # a glyph actually recognised in this frame (X / skip />>  / known exit) - never guess a corner.
            dx = adlearn.find_dialog_x(img)
            hit = adlearn.find_known(img)
            xy = dx or ((hit[0], hit[1]) if hit else None)
            if xy and not adlearn.is_bad(img, xy[0], xy[1]):
                log(f"ad: closing the ad at {xy}" + (f" ({hit[2]})" if hit and xy == (hit[0], hit[1]) else "") + " [landscape]")
                tap(xy, 2.5)
            else:
                time.sleep(1)
            continue
        if ad_playing(img):  # watch the video to its end (reward), exit buttons only afterwards
            t0 = max(t0, time.time() - 20)  # the "no exit button" timers start once the video is over
            time.sleep(1.5)
            continue
        if landing_page_bar(img):  # the ad was clicked through to its landing page: BACK out, don't hunt for its X
            log("ad: landing page opened (clicked through) - BACK to the ad")
            adb("shell", "input", "keyevent", "KEYCODE_BACK")
            time.sleep(1.5)
            continue
        dx = adlearn.find_dialog_x(img)
        if dx:
            log(f"ad: dialog X at {dx}: closing it")
            tap(dx, 1.5)
            continue
        sk = find_skip_text(img)
        hit = None if sk else adlearn.find_known(img)
        xy = sk or ((hit[0], hit[1]) if hit else find_ad_close_box(img))
        if xy and not sk and adlearn.is_bad(img, xy[0], xy[1]):  # mute / info / store openers look a bit like an X
            xy = None
        if xy and pressed.get((xy[0] // 50, xy[1] // 50), 0) >= 3:
            xy = None
        if xy:
            pressed[(xy[0] // 50, xy[1] // 50)] = pressed.get((xy[0] // 50, xy[1] // 50), 0) + 1
            if pending and time.time() - pending[2] < 4.5 and (abs(xy[0] - pending[1][0]) > 60 or abs(xy[1] - pending[1][1]) > 60):
                p = adlearn.learn_exit(pending[0], pending[1])  # pressing it revealed the real X: it was a step out
                if p:
                    log(f"ad: learned a new step-out button -> {os.path.basename(p)}")
                pending = None
            log(f"ad: closing the ad at {xy}" + (f" ({hit[2]})" if hit else ""))
            tap(xy, 2.5)
            continue
        if pending and time.time() - pending[2] < 6 and float((img[600:1500, 100:980].min(axis=2) > 235).mean()) > 0.45:
            # the button opened a white dialog (ad feedback, ...): not a way out. BACK closes it; never try it again
            adlearn.learn_bad(pending[0], pending[1])
            log("ad: that button opened a dialog, remembered as useless; BACK")
            pending = None
            adb("shell", "input", "keyevent", "KEYCODE_BACK")
            time.sleep(1.5)
            continue
        if time.time() - t0 > 25 and time.time() - last_try > 4.5:  # watch the video first, then look for the exit
            cands = adlearn.candidates(img, [(x, y) for x, y, tt in tried if time.time() - tt < 20])
            if cands:
                c = cands[0]
                tried.append((c[0], c[1], time.time()))
                last_try = time.time()
                pending = (img, c, last_try)
                log(f"ad: unknown button at {c[:2]} size {c[2]}x{c[3]}: trying it ({len(tried)})")
                cv2.imwrite(os.path.join(OUT, f"ad_try_{time.strftime('%H%M%S')}.png"), img)
                tap(c[:2], 1.5)
                continue
        if poked and not stored and time.time() - t0 > 45:
            # opening the store is harmless (we come back, nothing is ever installed): press the ad's big button
            stored = True
            log("ad: still no X, pressing the ad's main button (store may open, we come back)")
            tap((540, 2150), 3)
            continue
        if not poked and time.time() - t0 > 30:
            # some ads show no exit button until the screen is touched
            poked = True
            log("ad: no exit button after 30 s, tapping the ad once")
            cv2.imwrite(os.path.join(OUT, f"ad_noX_{time.strftime('%H%M%S')}.png"), shot())
            tap((540, 1100), 0.5)
            tried.clear()  # new buttons may have appeared after the touch
            continue
        if poked and not backed and time.time() - t0 > 75:
            # BACK often opens an end card that has the X
            backed = True
            log("ad: still no exit button, pressing BACK once to reach the end card")
            adb("shell", "input", "keyevent", "KEYCODE_BACK")
            time.sleep(2)
            tried.clear()
            continue
        time.sleep(1.5)
    else:
        log("ad: still showing after the time limit, pressing BACK")
        adb("shell", "input", "keyevent", "KEYCODE_BACK")
        time.sleep(2)
    if GAME_PKG not in focus():
        adb("shell", "monkey", "-p", GAME_PKG, "-c", "android.intent.category.LAUNCHER", "1")
        time.sleep(5)


def panel_open(img):
    """The build panel is up when its 'KINGDOM n' tab or the FREE / COMPLETE NOW bubble is visible above the cards
    (the bubble can hide the tab, or only its first letters)."""
    txt = " ".join(t for _, t in read(img, COMPLETE_BOX)).upper()
    return ("KINGDOM" in txt or re.search(r"DOM\s*\d", txt) is not None or "COMPLETE" in txt or "OMPLETE" in txt)


def open_panel():
    """The hammer button toggles the panel, so look first: tap it only when the panel is closed, then wait
    for the panel to slide up (polling, not a fixed sleep). Swipes on the strip happen only after this
    returned True (a swipe on the lobby would spin the camera)."""
    if panel_open(shot()):
        return True
    for _ in range(3):
        img = shot()
        xy = find_close_x(img)
        if xy:  # a popup (reward, milestone, ...) is covering the hammer / the panel's own tab text
            log(f"open_panel: popup at {xy} in the way: closing it")
            tap(xy, 1.0)
            continue
        tap(HAMMER, 0.5)
        for _ in range(6):
            if panel_open(shot()):
                return True
            time.sleep(0.25)
    return False


def close_panel():
    if panel_open(shot()):
        tap(SCENE, 1.5)
        if panel_open(shot()):
            tap(HAMMER, 1.5)  # the tap on the scene did not close it: toggle with the hammer


def front_card(first=True, img=None):
    """First card, from the left, that still has a price button. Finished buildings stay in the strip as
    green check marks (no price), so swipe right past them. Returns (screenshot, (price, x)) or None.
    `first`: go to the start of the strip first; later calls just look at `img` (the frame taken right after the
    last purchase) - the strip stays put, so no swipe and no extra screenshot are needed.
    The end of the strip is detected by a swipe that changes nothing (no blind repeated swiping)."""
    if first:
        time.sleep(0.3)  # the panel is still sliding up; swipes during that animation do nothing
        img = scroll_to_start()
    elif img is None:
        img = settle()
    for _ in range(14):
        ps = prices(img)
        if ps and ps[0][1] < 90:      # the leftmost button is cut off at the edge: a card hides further left
            scroll_cards(-1, 250)
            img = settle()
            continue
        if ps:
            return img, ps[0]
        if find_close_x(img) is not None:
            return None               # a reward popup sits over the strip: let the caller close it (never swipe on it)
        before = strip_sig(img)
        scroll_cards(+1, 900)         # no price on this page: all finished -> next page
        img = shot()
        if strip_same(before, strip_sig(img)):
            img = shot()
            if strip_same(before, strip_sig(img)):
                return None           # the swipe changed nothing: the end of the strip
    return None


COMPLETE_BOX = (0, 1400, 1080, 1700)    # build panel: the "KINGDOM n" tab (y~1419-1452) or the green "FREE
# (video) COMPLETE NOW" bubble hovers above the front unfinished card (its x moves)


_watch_times = []  # when a popup WATCH button was pressed lately
_cn_times = []   # when the FREE COMPLETE NOW button was pressed lately


def complete_now_button(img):
    """Centre of the green "FREE ▶ COMPLETE NOW" bubble (a free video finishes the front building), or None."""
    hit = [(sum(p[0] for p in b) / 4 + COMPLETE_BOX[0], sum(p[1] for p in b) / 4 + COMPLETE_BOX[1], t.upper())
           for b, t, _ in ocr(img[COMPLETE_BOX[1]:COMPLETE_BOX[3], COMPLETE_BOX[0]:COMPLETE_BOX[2]])[0] or []]
    if any("COMPLETE" in t or "OMPLETE" in t for _, _, t in hit) and any("FREE" in t for _, _, t in hit):
        for x, y, t in hit:
            if "COMPLETE" in t or "OMPLETE" in t:
                return int(x), int(y) + 20
    return None


# price ratio from one crown step to the next (0->1, 1->2, 2->3, 3->4), measured across several buildings:
# fairly stable regardless of the kingdom's overall price level
STEP_RATIOS = [1.30, 1.31, 1.47, 1.68]


def estimate_total_to_complete(price, crowns):
    """Coins needed to finish the front card in one go: `price` (the next purchase, known exactly) plus the
    remaining steps up to 5/5, estimated from the step-to-step ratios above (re-estimated after every real
    purchase, so an off guess for a later step never compounds)."""
    total, p = 0.0, float(price)
    for k in range(crowns, 5):
        total += p
        if k < 4:
            p *= STEP_RATIOS[k]
    return total


PROGRESS_BOX = (250, 1630, 850, 1730)    # build panel: "21/45" = steps done / steps in the whole kingdom
_kingdom_cost = 0.0      # estimated coins still needed to finish the whole kingdom (0 = unknown)
_kc_time = 0.0
_last_front_price = 0
_hold_need = 0.0     # coins the front card needs to be finished in one go ('saving up'); 0 = not holding
_hold_time = 0.0
HOLD_RECHECK_S = 240   # while holding, look at the panel again only this often (a free COMPLETE NOW video may be up)


def kingdom_progress(img):
    """(done, total) steps of the kingdom from the panel's progress bar, or None."""
    for _, t in read(img, PROGRESS_BOX):
        m = re.search(r"(\d+)\s*/\s*(\d+)", t)
        if m and int(m.group(2)) >= int(m.group(1)):
            return int(m.group(1)), int(m.group(2))
    return None


def scan_kingdom_cost():
    """Walk the strip and add up what every unfinished card still needs (next price known exactly, later steps
    estimated). This is the number that says whether the next KINGDOM is within reach."""
    global _kingdom_cost, _kc_time
    cards = scan_cards()
    total = sum(estimate_total_to_complete(c["price"], c["crowns"]) for c in cards)
    _kingdom_cost, _kc_time = total, time.time()
    return total, len(cards)


def green_price_buttons(img):
    """x of the green price pills in the card strip, left to right, found by colour (when the price text is not read)."""
    h = cv2.cvtColor(img[2110:2240], cv2.COLOR_BGR2HSV)
    m = cv2.morphologyEx(cv2.inRange(h, (38, 150, 170), (85, 255, 255)), cv2.MORPH_CLOSE, np.ones((9, 9), np.uint8))
    n, _, st, cent = cv2.connectedComponentsWithStats(m)
    return sorted(int(cent[i][0]) for i in range(1, n) if st[i, 2] > 150 and 60 < st[i, 3] < 160)


def build_all():
    """Build in the strip's own order: always the FRONT (leftmost) card, until it is complete (a finished
    building leaves the strip, so the next one becomes the front). If the front card is too expensive we
    wait for more coins; we never buy a card further back just because coins are spare.
    Returns (bought, price of the front card we are saving up for or None)."""
    if not open_panel():
        log("build: could not open the build panel")
        return 0, None
    global _last_front_price
    bought, target_price, stalls, recog_retry, next_img = 0, None, 0, 0, None
    if time.time() - _kc_time > 600:  # how much does the whole kingdom still cost? (decides "money is plentiful")
        total, n_cards = scan_kingdom_cost()
        prog = kingdom_progress(shot())
        log(f"kingdom: {n_cards} cards unfinished, ~{total:,.0f} coins to finish all"
            + (f" (steps {prog[0]}/{prog[1]})" if prog else ""))
        scroll_to_start()
    for i in range(60):
        found = front_card(first=(i == 0), img=next_img)
        next_img = None
        if found is None:
            img0 = shot()
            xy = find_close_x(img0)
            if xy:  # a reward/milestone popup over the strip - front_card() can't see past it either
                log(f"build: popup over the strip at {xy}: closing it")
                tap(xy, 1.0)
                recog_retry = 0
                continue
            prog = kingdom_progress(img0)
            if prog and prog[0] < prog[1] and recog_retry < 2:
                # the bar says steps are still missing but no price was read: look again before giving up
                recog_retry += 1
                log(f"build: nothing recognised but progress is {prog[0]}/{prog[1]} - looking again")
                time.sleep(1.0)
                continue
            if prog and prog[0] < prog[1] and _last_front_price:
                gp = green_price_buttons(shot())
                c0 = coins(shot())
                if gp and c0 is not None and c0 >= 3 * _last_front_price:
                    log(f"build: price text unreadable, coins {c0} are plenty: pressing the left-most green button x={gp[0]}")
                    tap((gp[0], BUTTON_Y), 1.6)
                    bought += 1
                    continue
            log("build: no unfinished building in the strip (all done?)")
            break
        recog_retry = 0
        img, (price, x) = found
        _last_front_price = price
        c_now = coins(img)
        need_now = estimate_total_to_complete(price, crowns_filled(img, x))
        # a free video completes the front building at once - worth it only when the coins cannot do it right now
        # (buying is far quicker than a 2-minute video); the OCR for the bubble is skipped when coins suffice
        cn = None if (c_now is not None and c_now >= need_now) else complete_now_button(img)
        if cn and c_now is not None and _kingdom_cost and c_now >= _kingdom_cost:
            cn = None  # plenty of coins for the whole kingdom: buying is quicker than watching a video
        now_t = time.time()
        _cn_times[:] = [t for t in _cn_times if now_t - t < 300]
        if cn and len(_cn_times) >= 3:  # three tries in 5 min and the button is still there: no video available now
            cn = None
        if cn:  # a free video completes the front building: take it, it costs no coins
            _cn_times.append(now_t)
            log(f"build: FREE COMPLETE NOW at {cn}: watching the video")
            tap(cn, 3)
            ride_ad()
            continue
        c = c_now
        if c is None:
            c = coins(shot())
            if c is None:
                break
        if find_close_x(img) is not None:  # a reward/gift popup is covering the panel
            tap(find_close_x(img), 1.0)
            continue
        crowns = crowns_filled(img, x)
        need_total = estimate_total_to_complete(price, crowns)
        target_price = need_total
        if need_total > c:
            global _hold_need, _hold_time
            _hold_need, _hold_time = need_total, time.time()
            log(f"build: front card {price} ({crowns}/5 crowns) - saving up to finish it in one go "
                f"(~{need_total:,.0f} total, have {c})")
            if time.time() - _kc_time > 600:  # how far is the next KINGDOM? (remaining steps and coins)
                total, n_cards = scan_kingdom_cost()
                prog = kingdom_progress(shot())
                log(f"kingdom: {n_cards} cards unfinished, ~{total:,.0f} coins to finish all (have {c}"
                    + (f", steps {prog[0]}/{prog[1]}" if prog else "") + ")")
            break
        log(f"build front card {price} ({crowns}/5 crowns, coins {c})")
        tap((x, BUTTON_Y), 0.9)
        bought += 1
        next_img = shot()          # this one frame serves both the coin check and the next card's price read
        c2 = coins(next_img)
        stalls = stalls + 1 if (c2 is not None and c2 == c) else 0
        if stalls >= 2:  # coins did not change: the tap does not buy (popup / animation)
            log("build: purchase did not register, handing control back")
            break
    close_panel()
    return bought, target_price


def motion(action, x, y):
    return subprocess.Popen([ADB, "shell", "input", "motionevent", action, str(x), str(y)],
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def explore_sling():
    """Pan the camera on the sling screen (horizontal drags in the scene above the sling) and save each view."""
    d = os.path.join(OUT, "explore")
    os.makedirs(d, exist_ok=True)
    for f in os.listdir(d):
        os.remove(os.path.join(d, f))
    cv2.imwrite(os.path.join(d, "00_start.png"), shot())
    moves = [("left_a", (800, 800, 250, 800)), ("left_b", (800, 800, 250, 800)),
             ("right_a", (250, 800, 900, 800)), ("right_b", (250, 800, 900, 800)),
             ("right_c", (250, 800, 900, 800)), ("right_d", (250, 800, 900, 800)),
             ("up", (540, 900, 540, 400)), ("down", (540, 400, 540, 1000))]
    for i, (name, (x1, y1, x2, y2)) in enumerate(moves, 1):
        adb("shell", "input", "swipe", str(x1), str(y1), str(x2), str(y2), "500")
        time.sleep(1.2)
        cv2.imwrite(os.path.join(d, f"{i:02d}_{name}.png"), shot())
    log("explore: saved shots/explore/*.png, stopping")


def aim_and_fire():
    """Hold the sling, track the face on a live 60 fps stream, release over the red target."""
    if not is_sling(shot()):  # never start a pull anywhere but on the sling screen
        log("aim: sling screen not visible, skipping")
        return
    if os.environ.get("SLING_EXPLORE"):  # look around: pan the camera left/right, save every view, stop
        explore_sling()
        raise SystemExit(0)
    try:
        res = aim_live.aim_and_release(log=log)
    except Exception as exc:  # never get stuck on the sling screen
        log(f"aim_live failed: {exc!r}")
        res = {}
    ensure_fired()


def aim_and_fire_screenshots():
    """Old screenshot-based aiming (1 s per capture); kept as a reference."""
    motion("DOWN", 540, 1640).wait()
    time.sleep(0.15)
    motion("MOVE", 540, 1800).wait()
    time.sleep(0.15)
    motion("MOVE", 540, 1950).wait()
    # two reads of the face; each capture timestamp is taken when the capture returns
    reads = []
    target_x = None
    for _ in range(6):
        t_cap = time.perf_counter()
        img = shot()
        t_done = time.perf_counter()
        fx, tx = sling.find_x(img)
        if tx is not None:
            target_x = tx
        # the screenshot shows the screen at about the middle of the capture call
        if fx is not None:
            reads.append(((t_cap + t_done) / 2, fx))
        if len(reads) >= 2 and reads[-1][0] - reads[0][0] > 0.9:
            break
    if len(reads) < 2:
        log("aim: marker not found, releasing now")
        motion("UP", 540, 1950).wait()
        ensure_fired()
        return
    (ta, xa), (tb, xb) = reads[0], reads[-1]
    # direction from the last two reads is ambiguous when the gap is ~1 s; use the half-period
    # model: the true direction is the one whose prediction matches the middle sample, if any
    best = None
    for d in (1, -1):
        err = sum(abs(sling.x_at(t, tb, d, xb) - x) for t, x in reads[:-1])
        if best is None or err < best[0]:
            best = (err, d)
    d = best[1]
    now = time.perf_counter()
    hit = sling.next_hit_time(now + FIRE_LEAD, tb, d, xb, target_x)
    if hit is None:
        motion("UP", 540, 1950).wait()
        ensure_fired()
        return
    # `adb shell input` takes ~0.05 s to deliver: start it that early
    wait = hit - time.perf_counter() - ADB_DELAY
    if wait > 0:
        time.sleep(wait)
    motion("UP", 540, 1950).wait()
    log(f"aim: reads={[(round(t - reads[0][0], 2), round(x)) for t, x in reads]} dir={d} "
        f"released {hit - time.perf_counter():+.3f}s from predicted hit")
    ensure_fired()


def ensure_fired():
    """If the sling is still on screen after the release, shoot with a plain pull-down swipe."""
    for _ in range(2):
        time.sleep(1.2)
        if not is_sling(shot()):
            return
        log("aim: sling still on screen, firing with a swipe")
        adb("shell", "input", "swipe", *map(str, SLING), "600")


def find_text(found, word):
    for b, t, _ in found:
        if word in t.strip().upper():
            return int(sum(p[0] for p in b) / 4), int(sum(p[1] for p in b) / 4)
    return None


FEED_RADIO = (110, 886)    # Facebook share dialog: "피드" check circle
POST_BTN = (538, 1149)   # Facebook share sheet: blue 게시 button
STORY_RADIO = (110, 1020)  # "내 스토리" check circle


def radio_on(img, p):
    """A checked circle is filled blue (Facebook blue) with a white tick; an unchecked one is a white ring.
    Count blue pixels in the circle (the tick in the middle is white, so a mean would miss it)."""
    x, y = p
    r = img[y - 22:y + 23, x - 22:x + 23].astype(int)
    blue = (r[..., 0] > 120) & (r[..., 2] < 110) & (r[..., 0] - r[..., 2] > 60)
    return float(blue.mean()) > 0.2


def select_story_only():
    """Make sure only 내 스토리 is ticked (feed unticked) before posting."""
    img = shot()
    if not radio_on(img, STORY_RADIO):
        tap(STORY_RADIO, 1)
        img = shot()
    if radio_on(img, FEED_RADIO):
        tap(FEED_RADIO, 1)
        img = shot()
    log(f"share dialog: story={radio_on(img, STORY_RADIO)} feed={radio_on(img, FEED_RADIO)}")


_share_tries = 0


SHARE_BTN = (230, 1970)    # KINGDOM RESTORED: blue SHARE pill
NEXT_BTN = (764, 1968)     # KINGDOM RESTORED: green NEXT KINGDOM pill


def kingdom_restored_look(img):
    """KINGDOM RESTORED without OCR: green NEXT pill + blue SHARE pill at the bottom. Returns None, or whether
    the white "+10 (dice)" bubble under SHARE is still there (share not yet posted)."""
    green = cv2.inRange(cv2.cvtColor(img[1900:2060, 540:1000], cv2.COLOR_BGR2HSV), (38, 150, 170), (85, 255, 255)).mean() / 255
    blue = cv2.inRange(cv2.cvtColor(img[1900:2040, 90:420], cv2.COLOR_BGR2HSV), (100, 150, 180), (125, 255, 255)).mean() / 255
    if green < 0.5 or blue < 0.5:
        return None
    return (img[2075:2125, 190:350].min(axis=2) > 235).mean() > 0.4


def fb_sheet(img):
    """The Facebook share sheet: its header band is Facebook blue."""
    h = img[75:150, 120:900].astype(int)
    return float((np.abs(h - np.array([173, 102, 74])).max(axis=2) < 25).mean()) > 0.5


def share_story_only():
    """On the Facebook share sheet: tick 내 스토리, untick 피드 (independent check boxes), press 게시. Fixed
    positions (measured), each state checked from the picture."""
    for _ in range(3):
        img = shot()
        if not fb_sheet(img):
            return
        if not radio_on(img, STORY_RADIO):
            tap(STORY_RADIO, 0.6)
            continue
        if radio_on(img, FEED_RADIO):
            tap(FEED_RADIO, 0.6)
            continue
        break
    log("share sheet: story only -> 게시")
    tap(POST_BTN, 1.0)
    for _ in range(12):  # wait for the sheet to go away
        if not fb_sheet(shot()):
            return
        time.sleep(0.4)
    adb("shell", "input", "keyevent", "KEYCODE_BACK")


def kingdom_restored_fast(img):
    """True when this was the KINGDOM RESTORED screen and we acted (share once if the bonus bubble is there,
    otherwise straight to NEXT KINGDOM)."""
    global _share_tries, _kingdom_changed, _kingdom_cost
    bonus = kingdom_restored_look(img)
    if bonus is None:
        return False
    if bonus and _share_tries < 3:
        _share_tries += 1
        log("kingdom restored: SHARE (+dice bubble) -> story only")
        tap(SHARE_BTN, 0.8)
        for _ in range(25):  # the Facebook sheet can take ~10 s to appear
            if fb_sheet(shot()):
                share_story_only()
                break
            time.sleep(0.3)
        return True
    log("kingdom restored: NEXT KINGDOM")
    tap(NEXT_BTN, 2.0)
    _kingdom_changed = True
    _kingdom_cost = 0.0
    _share_tries = 0
    return True


def kingdom_done(found):
    """KINGDOM RESTORED: SHARE first (it gives +10 rolls), back out of the share sheet, then NEXT KINGDOM."""
    global _share_tries, _kingdom_cost
    share = find_text(found, "SHARE")
    # the "+10 (dice)" bubble under SHARE is there only until the share was posted: no bubble -> straight to NEXT KINGDOM
    bonus = any(re.match(r"\+\s*\d+", r[1].strip()) for r in found)
    if share and bonus and _share_tries < 3:
        _share_tries += 1
        log("kingdom restored: SHARE for +10 rolls")
        tap(share, 4)
        dlg = ocr(shot())[0] or []
        sheet = " ".join(r[1] for r in dlg)
        if POST_SHARE and ("게시" in sheet or "Facebook" in sheet):
            # the user asked: always share to the STORY ("스토리 공유"), not the feed
            select_story_only()
            post = find_text(ocr(shot())[0] or [], "게시")
            log("share dialog: story selected, pressing 게시 (post)")
            tap(post or POST_BTN, 4)
        else:
            adb("shell", "input", "keyevent", "KEYCODE_BACK")  # close the Android share sheet
        time.sleep(2)
        img = shot()
        again = ocr(img)[0] or []
        if find_text(again, "NEXT KINGDOM") is None and find_text(again, "RESTORED") is None:
            adb("shell", "input", "keyevent", "KEYCODE_BACK")
            time.sleep(2)
            again = ocr(shot())[0] or []
        found = again
    nxt = find_text(found, "NEXT KINGDOM")
    if nxt:
        log("kingdom restored: NEXT KINGDOM")
        tap(nxt, 4)
        global _kingdom_changed
        _kingdom_changed = True  # new kingdom -> new prices: forget the old cheapest price
        _kingdom_cost = 0.0
        _share_tries = 0


PUZZLE_ICON = (134, 1989)  # lobby, bottom-left: purple puzzle piece (badge shows pieces owned)


def use_puzzle():
    """Idle task: open the puzzle event and fill the cheapest slots we can afford, then leave."""
    tap(PUZZLE_ICON, 3)
    img = shot()
    toks = [(sum(p[0] for p in b) / 4, sum(p[1] for p in b) / 4, t.strip()) for b, t, _ in (ocr(img)[0] or [])]
    if not any(k in " ".join(t for _, _, t in toks).upper() for k in ("GRAND PRIZE", "FINISH ALL")):
        tap(ANYWHERE, 1)
        log("puzzle: page did not open")
        return 0
    filled = 0
    for _ in range(6):
        have = None
        slots = []
        for x, y, t in toks:
            if re.fullmatch(r"\d{1,3}", t):
                if y > 1800 and 350 < x < 750:      # piece counter under the board
                    have = int(t)
                elif 780 < y < 1780:                # numbers printed on the puzzle slots
                    slots.append((int(t), int(x), int(y)))
        if have is None or not slots:
            break
        cost, x, y = min(slots)
        if cost > have:
            break
        log(f"puzzle: fill slot {cost} (have {have})")
        tap((x, y), 3)
        tap(ANYWHERE, 2)  # "TAP TO COLLECT" when a level completes
        filled += 1
        img = shot()
        toks = [(sum(p[0] for p in b) / 4, sum(p[1] for p in b) / 4, t.strip()) for b, t, _ in (ocr(img)[0] or [])]
    tap(BACK_BTN, 2.5)
    return filled


def claim_weekly():
    """Idle task: open WEEKLY GOALS (clipboard icon) and press every green CLAIM, then close."""
    tap(WEEKLY, 2.5)
    claimed = 0
    for _ in range(8):
        img = shot()
        hit = None
        for b, t, _ in ocr(img)[0] or []:
            if t.strip().upper() == "CLAIM":
                hit = (int(sum(p[0] for p in b) / 4), int(sum(p[1] for p in b) / 4))
                break
        if not hit:
            break
        tap(hit, 2.5)
        tap(ANYWHERE, 1.5)  # "TAP TO COLLECT" popup
        claimed += 1
    img = shot()
    xy = find_close_x(img)
    tap(xy or (971, 351), 1.5)
    tap(ANYWHERE, 1.5)
    log(f"weekly goals: claimed {claimed}")
    return claimed


def run_ads_only(max_ads):
    """CLI `python bot.py ads N`: ignore rolling/building/minigames entirely (none of those can even trigger
    without a ROLL tap) and just watch up to N free videos in a row, handling only what can actually stand
    between one video and the next: a stray event page, an ad/app already in front, a popup, or a leftover
    share sheet from a kingdom that just finished."""
    watched = 0
    log(f"ads-only mode: watching up to {max_ads} free videos")
    while watched < max_ads:
        img = shot()
        if landscape(img):  # a rotated ad: ride_ad() only acts on a recognised glyph, never a blind coordinate
            ride_ad()
            continue
        ba = find_back_arrow(img)
        if ba:  # a stray event page: leave it so the lobby (and its video bubble) comes back
            log(f"back arrow at {ba}: leaving this page")
            tap(ba, 2.0)
            continue
        f = focus()
        if f and (is_ad_focus(f) or is_ad_any(f) or GAME_PKG not in f):  # an ad (or another app) is already in front
            if GAME_PKG not in f and not is_ad_any(f):
                log(f"another app has focus ({f[-50:]}): leaving it")
                leave_other_app(f)
            else:
                xy = find_skip_text(img) or find_ad_close(img)
                if not xy and not ad_playing(img):  # only once the video itself is done - don't cut it short
                    xy = find_google_play_text(img)
                if xy and adlearn.is_bad(img, xy[0], xy[1]):
                    xy = None
                if xy:
                    log(f"ad on screen: closing at {xy}")
                    tap(xy, 2.5)
                else:
                    log("ad on screen without X: waiting / poking")
                    ride_ad()
            continue
        if find_close_x(img) is not None:  # a popup sits on top of the board
            tap(find_close_x(img), 1.2)
            continue
        if fb_sheet(img):  # a kingdom-restored share sheet left open
            share_story_only()
            continue
        if time.time() - _last_ad > 20 and watch_ad(img):
            watched += 1
            log(f"ads mode: {watched}/{max_ads} watched")
            continue
        time.sleep(2)
    log(f"ads-only mode: done, watched {watched} ads")


def main():
    require_phone()
    # `python bot.py N` plays normally for up to N rolls; `python bot.py ads N` ignores rolling/building and
    # just watches up to N free videos back-to-back (see run_ads_only, a separate leaner loop).
    if len(sys.argv) > 1 and sys.argv[1].lower() == "ads":
        run_ads_only(int(sys.argv[2]) if len(sys.argv) > 2 else 10000)
        return
    max_rolls = int(sys.argv[1]) if len(sys.argv) > 1 else 20
    touch_ok()
    rolls = unknown = idle = pay_tries = back_tries = fight_n = pin_n = loading_n = 0
    since_check = 3  # first lobby loop already looks at the coins
    cur_step = None  # xN step we believe is set; reset after popups / waits
    stall_since = time.time()
    last_was_roll = False
    busy_n = 0
    _last_coins = 0
    btn_hist = {}   # (button, x, y) -> (times pressed, last time): a button that never works is left alone
    steal_n = 0
    pinball_n = 0
    last_roll_t = 0.0
    popup_after_roll = 0
    no_energy_until = 0.0
    need = 0  # coins needed before trying to build again
    refilling = False  # True while watching ads back-to-back after money+energy both ran out, until any energy is back
    while rolls < max_rolls:
        img = shot()
        if landscape(img):  # a rotated ad: ride_ad() only acts on a recognised glyph, never a blind coordinate
            ride_ad()
            continue
        if roll_visible(img) or roll_busy(img) or ad_playing(img):
            touch_ok()
        elif time.time() - _last_ok > STUCK_S:
            recover(img, time.time() - _last_ok)
            continue
        ba = find_back_arrow(img)
        if ba:  # an event page / mini-game is open: leave through its back arrow
            log(f"back arrow at {ba}: leaving this page")
            tap(ba, 2.0)
            continue
        if last_roll_t and time.time() - last_roll_t < 8 and (find_close_x(img) is not None or adlearn.find_dialog_x(img)):
            # a popup (buy-rolls offer, piggy bank...) right after ROLL: the dice are gone whatever the number says
            last_roll_t = 0.0
            popup_after_roll += 1
            if popup_after_roll >= 2:
                no_energy_until = time.time() + 300
                popup_after_roll = 0
                _E["val"] = None
                log("ROLL keeps opening an offer popup: treating the dice as used up for 5 minutes")
        if roll_busy(img):  # dice on the board, ROLL dimmed: the animation, or the game waiting for the next tap
            busy_n += 1
            if busy_n < 4:
                time.sleep(0.3)
                continue
            log("roll button dimmed for a while: tapping ROLL to go on")
            tap(ROLL, ROLL_WAIT)
            busy_n = 0
            rolls += 1
            last_was_roll = True
            continue
        busy_n = 0
        e = energy_est(img, last_was_roll)
        last_was_roll = False
        if time.time() < no_energy_until and e is not None:
            e = 0
        c = None
        if e is not None and not roll_visible(img):
            e = None  # an overlay covers ROLL: treat as popup
        if e is None:
            cur_step = None
            if is_sling(img):  # the sling screen has no text: recognise it by its strap
                log("sling screen detected: aim")
                aim_and_fire()
                time.sleep(2.5)
                continue
            hsv_p = cv2.cvtColor(img[1960:2130, 60:870], cv2.COLOR_BGR2HSV)
            if cv2.inRange(hsv_p, (140, 110, 190), (170, 255, 255)).mean() / 255 > 0.35:
                # FRIENDS MULTIPLIER pinball: only the three big pink buttons at the bottom matter (each drops a
                # ball). The results screen (COLLECT, ...) shares this pink colouring, so check for a real
                # button first - otherwise this would keep mashing pinball buttons on a screen that is done.
                hit = next(((int(sum(p[0] for p in b) / 4), int(sum(p[1] for p in b) / 4)) for b, t, _ in ocr(img)[0] or []
                            if t.strip().upper().strip("!") in BUTTONS), None)
                if hit:
                    log(f"pinball: results screen, button at {hit}")
                    tap(hit, 1.5)
                    pinball_n = 0
                    continue
                if pinball_n >= 8:  # far more balls than any real round needs: something is off, back off
                    log("pinball: too many presses without it ending, backing off")
                    pinball_n = 0
                    time.sleep(2)
                    continue
                pinball_n += 1
                log(f"pinball: pressing bottom button #{pinball_n % 3 + 1}")
                tap(PINBALL_BTNS[pinball_n % 3], 1.8)
                continue
            hsv_f = cv2.cvtColor(img[2000:2300], cv2.COLOR_BGR2HSV)
            if (((hsv_f[..., 0] >= 163) | (hsv_f[..., 0] <= 4)) & (hsv_f[..., 1] > 90) & (hsv_f[..., 2] > 170)).mean() > 0.25:
                fight_n += 1  # FIGHT (rock-paper-scissors): the pink panel with three round move buttons; any move
                log(f"fight screen: move #{fight_n % 3 + 1}")
                tap(FIGHT_MOVES[fight_n % 3], 1.5)
                continue
            if fb_sheet(img):  # Facebook share sheet (also when the bot is started with it open)
                share_story_only()
                continue
            if kingdom_restored_fast(img):
                continue
            if video_craze_screen(img):  # its own event: watch every unlocked tier, not just one popup watch
                use_video_craze()
                continue
            if paid_offer_screen(img):  # a real-money funnel: claim whatever is actually free, then leave
                use_paid_offer()
                continue
            f = focus()
            if f and (is_ad_focus(f) or is_ad_any(f) or GAME_PKG not in f):  # an ad (or another app) is in front
                if GAME_PKG not in f and not is_ad_any(f):
                    log(f"another app has focus ({f[-50:]}): leaving it")
                    leave_other_app(f)
                else:
                    xy = find_skip_text(img) or find_ad_close(img)
                    if not xy and not ad_playing(img):  # only once the video itself is done - don't cut it short
                        xy = find_google_play_text(img)
                    if xy and adlearn.is_bad(img, xy[0], xy[1]):
                        xy = None
                    if xy:
                        log(f"ad on screen: closing at {xy}")
                        tap(xy, 2.5)
                    else:
                        log("ad on screen without X: waiting / poking")
                        ride_ad()
                continue
            found = ocr(img)[0] or []
            wt = [(int(sum(p[0] for p in b) / 4), int(sum(p[1] for p in b) / 4)) for b, t, _ in found
                  if t.strip().upper().startswith("WATCH") and len(t.strip()) <= 14]
            wt = [p for p in wt if not watch_locked(img, *p)]  # skip reward-path tiles not unlocked yet
            _watch_times[:] = [x for x in _watch_times if time.time() - x < 300]
            if wt and len(_watch_times) < 3 and not re.search(r"[$₩€£]", " ".join(r[1] for r in found)):
                # an offer popup with a WATCH (free video) button: take it, same as the lobby bubble
                _watch_times.append(time.time())
                log(f"popup WATCH button at {wt[0]}: watching the video")
                tap(wt[0], 3)
                if is_ad_focus(focus()):
                    ride_ad()
                continue
            for b, t, _ in found:  # game guide: "TAP & HOLD" with a hand on the target just below the words
                if re.search(r"TAP\s*[&8A]?\s*(AND\s*)?HOLD", t.strip().upper()):
                    hx = int(sum(p[0] for p in b) / 4)
                    hy = int(sum(p[1] for p in b) / 4) + 155
                    log(f"guide: TAP & HOLD -> holding {hx},{hy}")
                    adb("shell", "input", "swipe", str(hx), str(hy), str(hx), str(hy), "1800")
                    time.sleep(1.5)
                    break
            else:
                hx = None
            if hx is not None:
                continue
            all_txt = " ".join(r[1] for r in found).upper()
            locked = "UNLOCK" in all_txt or bool(re.search(r"[$₩€£]|W\s?\d", all_txt))  # offer pages: chained FREE, prices
            now_b = time.time()
            for k in [k for k, v in btn_hist.items() if now_b - v[1] > 90]:
                del btn_hist[k]
            for b, t, _ in found:
                tok = t.strip().upper().strip("!")
                if tok in BUTTONS:
                    cx = int(sum(p[0] for p in b) / 4)
                    cy = int(sum(p[1] for p in b) / 4)
                    if tok == "FREE" and locked:
                        continue  # a FREE that sits behind a padlock / on a paid offer page is not a gift
                    key = (tok, cx // 50, cy // 50)
                    n_pressed = btn_hist.get(key, (0, 0))[0]
                    if n_pressed >= (3 if tok == "FREE" else 6):
                        continue  # pressed again and again with no effect: leave it, close the page with its X
                    btn_hist[key] = (n_pressed + 1, now_b)
                    log(f"button '{t}' at {cx},{cy}" + (f" (press {n_pressed + 1}/3)" if tok == "FREE" or n_pressed else ""))
                    tap((cx, cy), 1.0)
                    break
            else:
                cx = None
            if cx is not None:
                continue
            texts = " ".join(r[1] for r in found).upper()
            if "CHOOSE YOUR MOVE" in texts or "BEFORE TIME" in texts or ("MOVE" in texts and "RUNS OUT" in texts):
                # FIGHT mini-game (rock-paper-scissors, best of 3): pick a move, any move; it is random
                fight_n += 1
                log(f"fight: pick move #{fight_n % 3 + 1}")
                tap(FIGHT_MOVES[fight_n % 3], 2.5)
                continue
            # Payment first: the Google Play sheet also says "Dice Dreams", so it must be checked before
            # anything that looks for the game's name. Never confirm; Android BACK dismisses it.
            if "GOOGLE PLAY" in texts or "원탭" in texts or "구매" in texts or "SPECIAL OFFER" in texts \
                    or "₩" in texts or "포인트" in texts:
                log("Google Play purchase sheet: Android BACK (never confirm)")
                lock_buy_zone()
                adb("shell", "input", "keyevent", "KEYCODE_BACK")
                time.sleep(1.5)
                continue
            if "LOADING" in texts or ("DICE DREAMS" in texts and "TOWN" in texts):  # splash: just wait
                loading_n += 1
                log("loading screen: waiting")
                if loading_n > 20:  # ~80 s: not a loading screen after all; stop waiting and act
                    loading_n = 0
                else:
                    time.sleep(4)
                    continue
            cx_ = find_close_x(img)
            if cx_ is not None:  # an X is there: always press the X (never the blue "?" at the top-left)
                log(f"X button at {cx_}: closing")
                tap(cx_, 1.5)
                continue
            if any(k in texts for k in ("GRAND PRIZE", "FINISH ALL", "LEVELS", "LEADERBOARD", "ALBUM")):
                log("event/sub screen: back arrow (top-left)")
                back_tries += 1
                tap(BACK_BTNS[back_tries % len(BACK_BTNS)], 2)  # arrow height differs per page
                continue
            if "NEXT KINGDOM" in texts or "RESTORED" in texts:
                kingdom_done(found)
                continue
            xy = find_close_x(img)  # red round X (ads, offers, payment, invite, ...)
            if xy or re.search(r"[$₩€£]|\bW\s?\d|BREAK NOW|PACK\b", texts):
                lock_buy_zone()
            if xy:
                log(f"close popup (red X) at {xy}")
                tap(xy, 1.2)
                continue
            if re.search(r"[$₩€£]|\bW\s?\d|\d\s*원|\bUSD\b|\bKRW\b|BREAK NOW|PACK\b", texts):
                # payment screen: close, never buy. Prefer the real "X" found by OCR.
                pos = None
                for b, t, _ in found:
                    if t.strip().upper() in ("X", "×"):
                        px, py = sum(p[0] for p in b) / 4, sum(p[1] for p in b) / 4
                        if px > 700 and py < 800:
                            pos = (int(px), int(py))
                            break
                pos = pos or PAY_CLOSE[pay_tries % len(PAY_CLOSE)]
                pay_tries += 1
                log(f"payment screen: close with top-right X at {pos}")
                tap(pos, 1.2)
                continue
            if re.search(r"TAP\W{0,2}TO\b", texts):  # "TAP TO CONTINUE/COLLECT" (OCR gives "TAP+TO"): touch anywhere
                log("tap to continue")
                tap(ANYWHERE, 1.0)
                continue
            for b, t, _ in found:  # ads / offers / payment popups: close with X
                if t.strip().upper() in ("X", "×") and sum(p[0] for p in b) / 4 > 700 \
                        and sum(p[1] for p in b) / 4 < 800:
                    cx = int(sum(p[0] for p in b) / 4)
                    cy = int(sum(p[1] for p in b) / 4)
                    log(f"close popup X at {cx},{cy}")
                    tap((cx, cy), 1.0)
                    break
            else:
                cx = None
            if cx is not None:
                continue
            if "ROLL BOOST" in texts or "CARD LEVEL" in texts:  # result popup
                log("result popup: tap to continue")
                tap(NEUTRAL, 1.0)
                continue
            steal_bar = re.search(r"\d[\d,]*\s*/\s*\d{2},\d{3}", texts)  # "0 / 19,000" progress bar
            px = img[225, 700].astype(int)  # BGR; purple banner = STEAL, blue banner = attack
            purple_banner = "KINGDOM" in texts and px[1] < 100 and px[0] > 180 and px[2] > 100
            if "STEAL" in texts or steal_bar or purple_banner or "STOLEN" in texts or "TREASURE" in texts:
                tiles = steal_tiles(img)
                if tiles:  # the stepping-tile variant: the tutorial hand points at the right-most tile
                    steal_n += 1
                    order = [len(tiles) - 1] + list(range(len(tiles) - 1))
                    spot = tiles[order[steal_n % len(order)]]
                    log(f"steal tiles: tapping {spot}")
                    tap(spot, 1.6)
                    continue
                log("steal minigame: tap STEAL")
                tap(STEAL, 1.0)  # just keep touching STEAL
                continue
            if re.search(r"\w+['’`]S\s*KINGDOM", texts) and "CARDS" not in texts:
                if is_sling(img):  # already on the sling screen (e.g. after a retry)
                    aim_and_fire()
                    time.sleep(2.5)
                    continue
                pins = find_pins(img)
                pin_n += 1
                # pick a pin (top one first, then the others if the tap did not open the sling screen)
                spot = pins[(pin_n - 1) % len(pins)] if pins else TARGET
                log(f"attack: pick target pin {spot} ({len(pins)} pins found)")
                tap(spot, 1.5)
                opened = False
                for _ in range(10):  # the camera swoops to the sling: it takes 4-6 s
                    if is_sling(shot()):
                        opened = True
                        break
                    time.sleep(0.6)
                if not opened:
                    log("attack: sling screen did not open, trying the next pin")
                    continue
                pin_n = 0
                aim_and_fire()
                time.sleep(2.5)
                continue
            unknown += 1
            gm = cv2.inRange(cv2.cvtColor(img[1900:2060, 540:1000], cv2.COLOR_BGR2HSV), (38, 150, 170), (85, 255, 255))
            if float((gm > 0).mean()) > 0.55:  # big green pill at the bottom right (NEXT KINGDOM / OK ...): go on
                log("big green button at the bottom right: tapping it")
                tap((764, 1968), 3)
                continue
            dx = adlearn.find_dialog_x(img)
            if dx:  # a white dialog with a black X: just press it
                log(f"dialog X at {dx}")
                tap(dx, 1.5)
                continue
            # new screen with no X / TAP / COLLECT: nearly always a tap on the right side or anywhere moves on.
            # Never stop; keep a picture of it so it can be reviewed later.
            if unknown in (1, 30, 90):
                name = f"unknown_{time.strftime('%H%M%S')}.png"
                cv2.imwrite(os.path.join(OUT, name), img)
                with open(os.path.join(OUT, "unknown_log.txt"), "a", encoding="utf-8") as fh:
                    fh.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')} {name} #{unknown} texts: {texts[:300]}" + chr(10))
                log(f"unknown screen: saved {name} + its texts (shots/unknown_log.txt), tapping around")
            if unknown % 12 == 0:
                adb("shell", "input", "keyevent", "KEYCODE_BACK")  # now and then a BACK (never confirms anything)
                time.sleep(1.5)
            else:
                tap(UNKNOWN_TAPS[unknown % len(UNKNOWN_TAPS)], 1.0)
            continue
        unknown = 0
        if refilling and e >= 1:
            refilling = False
            log(f"energy back to {e}: back to playing")
        if e >= 1:  # energy first: spend it all, down to 0
            idle = 0
            if find_close_x(img) is not None:  # a popup sits on top of the board: never tap ROLL/xN
                lock_buy_zone()
                tap(find_close_x(img), 1.2)
                continue
            # ads are watched only once energy and money are both spent (see the e < 1 branch below);
            # while there's still dice or coins to use, just keep rolling/building.
            # priority 1: money -> kingdom upgrades. The hammer's red badge counts upgrades affordable right
            # now and updates live, so check it every loop (no throttle) instead of waiting on a timer.
            if not free_mode:
                hb = hammer_badge(img)
                holding = False
                if _hold_need and time.time() - _hold_time < HOLD_RECHECK_S:
                    cnow = coins(img)
                    if cnow is not None:
                        _last_coins = cnow
                    holding = (cnow or 0) < _hold_need
                if hb and holding:
                    hb = 0   # the badge only means "some step is affordable"; we are saving up for the whole card
                if hb:
                    log(f"hammer badge {hb}: upgrades available, building")
                    n, _ = build_all()
                    if n:
                        cur_step = None
                        continue
                else:
                    since_check += 1
                    rich = bool(_kingdom_cost) and (_last_coins or 0) >= _kingdom_cost
                    if holding:
                        since_check = 0
                    if since_check >= (1 if rich else (2 if _kingdom_cost else 4)):
                        since_check = 0
                        cc = coins(img)
                        if cc is not None:
                            _last_coins = cc
                        # the next KINGDOM within reach (coins cover everything still unbuilt): upgrades come
                        # first, whatever the 500k rule says
                        finish = bool(_kingdom_cost) and cc is not None and cc >= _kingdom_cost
                        if cc is not None and (cc >= BUILD_AT or finish):
                            log(f"coins {cc} cover the whole kingdom (~{_kingdom_cost:,.0f}): upgrades first" if finish
                                else f"coins {cc} >= {BUILD_AT}: upgrading the kingdom")
                            n, _ = build_all()
                            if n:
                                cur_step = None
                                continue
            if not free_mode and maybe_trail(img):
                cur_step = None
                continue
            if not free_mode:
                # the "MAX xN" bubble names the best multiplier on offer right now: match it when it's shown.
                # When it isn't shown at all, leave the multiplier alone and just roll.
                mx = read_max_mult(img)
                if mx:
                    if time.time() - _steps_checked > 1800:  # the steps on offer change slowly (x5 only sometimes)
                        discover_steps()
                    want = mx if mx <= max(1, e) else best_step(e)
                    if cur_step != want:
                        ok = set_multiplier(want)
                        shown = badge_value(shot())
                        if ok:
                            cur_step = want
                            log(f"multiplier -> x{want}")
                        elif shown is not None and shown <= e:
                            # could not reach the ideal step, but the one on screen is affordable: ROLL anyway,
                            # energy comes first (never sit idle with energy left)
                            cur_step = shown
                            log(f"multiplier x{want} unreachable, rolling at x{shown}")
                        else:
                            # the shown step costs more energy than we have (would open a "buy rolls" offer)
                            # or the board is covered: re-check the screen instead of rolling
                            cur_step = None
                            forget_steps()  # the cycle may have changed: measure it again next time
                            log("multiplier unknown/too high, re-checking")
                            time.sleep(1)
                            continue
            log(f"roll #{rolls + 1} energy={e}")
            last_roll_t = time.time()
            tap(ROLL, ROLL_WAIT)
            rolls += 1
            last_was_roll = True
            continue
        # no energy: spend coins on the kingdom, then watch ads back-to-back until any energy is back
        if not refilling:
            global _ads_in_batch
            refilling = True
            _ads_in_batch = 0
            log("dice/money used up: watching ads until energy is back")
        c = coins(img)
        # `need` is only a hint to avoid opening the panel every 15 s; it is dropped after a new
        # kingdom (prices change) and every 8th idle loop, so a stale value can never block building
        global _kingdom_changed
        if idle % 8 == 0 or _kingdom_changed:
            need = 0
            _kingdom_changed = False
        if c is None or c >= need:
            n, min_price = build_all()
            need = min_price or 0
            if n:
                need = 0
                continue
        idle += 1
        cur_step = None
        # no energy and nothing to build: the VIDEO bonus-ad icon pays more than the lobby bubble, so try it
        # first; only once it's on cooldown (or absent) do we fall back to the regular lobby bubble
        if time.time() - stall_since > 3600:
            stall_since = time.time()
        if time.time() - _last_ad > 20:
            if try_video_event(img):
                idle = 0
                continue
            if watch_ad():
                idle = 0
                continue
        if idle % 40 == 1:  # nothing to roll or build: collect free rewards (every ~10 min)
            claim_weekly()
            use_puzzle()
            continue
        if idle > MAX_IDLE:
            log("no energy for a long time, stopping")
            return
        log(f"energy low, waiting (coins={c}, next build needs {need})")
        time.sleep(15)  # poll often: energy can jump (rewards) and popups may appear
    log("done", rolls, "rolls")


if __name__ == "__main__":
    main()
