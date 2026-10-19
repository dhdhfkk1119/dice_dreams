"""Measure how long one `adb shell input motionevent` call takes (the release delay)."""
import os
import statistics
import subprocess
import time

ADB = os.path.join(os.path.dirname(os.path.abspath(__file__)), "tools", "platform-tools", "adb.exe")
ts = []
for _ in range(10):
    t = time.perf_counter()
    subprocess.run([ADB, "shell", "echo", "x"], capture_output=True)
    ts.append(time.perf_counter() - t)
print("adb shell echo: median %.3f s, min %.3f, max %.3f" % (statistics.median(ts), min(ts), max(ts)))
t = time.perf_counter()
subprocess.run([ADB, "shell", "echo a; echo b; echo c"], capture_output=True)
print("three commands in one shell call: %.3f s" % (time.perf_counter() - t))
