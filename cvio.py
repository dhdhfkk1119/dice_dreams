"""cv2.imread fails silently (returns None) on Windows paths with non-ASCII characters
(e.g. a folder named in Korean), because it opens the file with the ANSI codepage
instead of Unicode. Read the bytes with Python's own (Unicode-safe) file I/O and
hand them to cv2.imdecode instead.
"""
import numpy as np
import cv2


def imread(path, flags=cv2.IMREAD_COLOR):
    try:
        buf = np.fromfile(path, dtype=np.uint8)
    except OSError:
        return None
    if buf.size == 0:
        return None
    return cv2.imdecode(buf, flags)
