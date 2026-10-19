# Dice Dreams bot

ADB (USB) player for the mobile game Dice Dreams. It rolls the dice at the multiplier the "MAX xN" bubble
names (or whatever is already set, if that bubble isn't shown), upgrades the kingdom one building at a time
(saves up for the whole front card instead of buying single steps), watches free videos once money and
energy both run out (until any energy is back, no cap on how many), and handles the pop-ups, mini-games
(sling, steal, fight, pinball) and the kingdom-restored share screen (story only, never the feed).

Never presses a real-money purchase button (payment screens are closed with X / BACK).

    python bot.py <max_rolls>      # play normally for up to this many rolls
    python bot.py ads <max_ads>    # ignore rolling/building: just watch up to this many free videos in a row

Requires the phone serial in `bot.py`, `adb` at `tools/platform-tools/adb.exe` (not included),
`opencv-python`, `numpy`, `rapidocr-onnxruntime`, `av`.
