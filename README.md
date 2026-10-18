# Dice Dreams bot

ADB (USB) player for the mobile game Dice Dreams. It rolls the dice with the highest affordable multiplier,
upgrades the kingdom (front card first), watches free videos in batches of 10, and handles the pop-ups,
mini-games (sling, steal, fight, pinball) and the kingdom-restored share screen.

Never presses a real-money purchase button (payment screens are closed with X / BACK).

    python bot.py <max_rolls>

Requires the phone serial in `bot.py`, `adb` at `tools/platform-tools/adb.exe` (not included),
`opencv-python`, `numpy`, `rapidocr-onnxruntime`, `av`.
