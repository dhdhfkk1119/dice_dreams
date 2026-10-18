import subprocess, sys, time, os

ADB = r"D:\dice_dreams\tools\platform-tools\adb.exe"
OUT = r"D:\dice_dreams\shots"
ROLL = (538, 1977)
os.makedirs(OUT, exist_ok=True)


def adb(*a):
    return subprocess.run([ADB, *a], capture_output=True)


def shot(name):
    adb("shell", "screencap", "-p", "/sdcard/s.png")
    path = os.path.join(OUT, name)
    adb("pull", "/sdcard/s.png", path)
    return path


n = int(sys.argv[1]) if len(sys.argv) > 1 else 3
for i in range(n):
    adb("shell", "input", "tap", str(ROLL[0]), str(ROLL[1]))
    time.sleep(4)
    print(shot(f"roll_{i:02d}.png"), flush=True)
