"""Where does the bot spend its time? Sums the seconds that follow each kind of log line (capped per gap)."""
import collections
import datetime
import glob
import os
import re
import sys

since = sys.argv[1] if len(sys.argv) > 1 else "00:00:00"
day_filter = sys.argv[2] if len(sys.argv) > 2 else None
rows = []
for f in sorted(glob.glob(os.path.join(os.path.dirname(os.path.abspath(__file__)), "logs", "*.log"))):
    day = os.path.basename(f)[:10]
    if day_filter and day != day_filter:
        continue
    for line in open(f, encoding="utf-8", errors="ignore"):
        m = re.match(r"(\d\d):(\d\d):(\d\d) (.*)", line)
        if m:
            t = datetime.datetime.strptime(day + " " + ":".join(m.groups()[:3]), "%Y-%m-%d %H:%M:%S")
            rows.append((t, m.group(4).strip()))
rows = [r for r in rows if r[0].strftime("%H:%M:%S") >= since or day_filter is None]
print(len(rows), "lines", rows[0][0], "->", rows[-1][0])
cat, cnt = collections.Counter(), collections.Counter()


def key(msg):
    return re.sub(r"[0-9,]+", "N", msg)[:60]


for (t, m), (t2, _) in zip(rows, rows[1:]):
    d = min((t2 - t).total_seconds(), 600)
    cat[key(m)] += d
    cnt[key(m)] += 1
tot = sum(cat.values())
print(f"total {tot / 3600:.2f} h")
for k, v in cat.most_common(30):
    print(f"{v / 3600:6.2f} h {100 * v / tot:5.1f}% {cnt[k]:5d}  {k}")
