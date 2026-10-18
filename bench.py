"""Timing of the pieces of the roll loop (run with the phone in the lobby, no bot running)."""
import os
import statistics
import time

os.environ["ANDROID_SERIAL"] = "R3KL20CWEMT"
import bot  # noqa: E402


def timeit(name, f, n=6):
    ts = []
    for _ in range(n):
        t = time.perf_counter()
        f()
        ts.append(time.perf_counter() - t)
    print(f"{name:28s} median {statistics.median(ts) * 1000:6.0f} ms   min {min(ts) * 1000:6.0f}   max {max(ts) * 1000:6.0f}")


img = bot.shot()
timeit("screencap (adb exec-out)", bot.shot)
timeit("energy OCR", lambda: bot.energy(img), 4)
timeit("coins OCR", lambda: bot.coins(img), 4)
timeit("roll_visible + find_close_x", lambda: (bot.roll_visible(img), bot.find_close_x(img)), 20)
timeit("adb shell input tap (harmless)", lambda: bot.adb("shell", "input", "tap", "540", "300"), 6)
timeit("focus() dumpsys", bot.focus, 4)

try:
    import rawtouch
    t = rawtouch.Touch()
    timeit("sendevent tap (persistent)", lambda: t.tap(540, 300), 10)
    t.close()
except Exception as exc:  # noqa: BLE001
    print("rawtouch failed:", exc)
