"""Live screen stream from the phone: adb screenrecord (H.264) -> PyAV -> numpy frames.

Each frame comes with the wall-clock time at which we decoded it (time.perf_counter()).
"""
import subprocess
import threading
import time

import av
import numpy as np

ADB = r"D:\dice_dreams\tools\platform-tools\adb.exe"


class Stream:
    def __init__(self, size="540x1170", bitrate=6_000_000, seconds=180):
        self.size = size
        self.proc = subprocess.Popen(
            [ADB, "exec-out", "screenrecord", "--output-format=h264", "--size", size,
             "--bit-rate", str(bitrate), "--time-limit", str(seconds), "-"],
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, bufsize=0)
        self.codec = av.CodecContext.create("h264", "r")
        self.lock = threading.Lock()
        self.latest = None          # (t_decoded, bgr frame)
        self.count = 0
        self.alive = True
        self.t = threading.Thread(target=self._run, daemon=True)
        self.t.start()

    def _run(self):
        while self.alive:
            chunk = self.proc.stdout.read(65536)
            if not chunk:
                break
            try:
                packets = self.codec.parse(chunk)
                for pkt in packets:
                    for frame in self.codec.decode(pkt):
                        t = time.perf_counter()
                        img = frame.to_ndarray(format="bgr24")
                        with self.lock:
                            self.latest = (t, img)
                            self.count += 1
            except av.error.InvalidDataError:
                continue
        self.alive = False

    def get(self):
        with self.lock:
            return self.latest

    def close(self):
        self.alive = False
        try:
            self.proc.kill()
        except Exception:
            pass
