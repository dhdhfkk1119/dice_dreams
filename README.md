# Dice Dreams bot

ADB (USB) player for the mobile game Dice Dreams. It rolls the dice at the multiplier the "MAX xN" bubble
names (or whatever is already set, if that bubble isn't shown), upgrades the kingdom one building at a time
(saves up for the whole front card instead of buying single steps), watches free videos once money and
energy both run out (until any energy is back, no cap on how many), and handles the pop-ups, mini-games
(sling, steal, fight, pinball) and the kingdom-restored share screen (story only, never the feed).

Never presses a real-money purchase button (payment screens are closed with X / BACK).

    python bot.py <max_rolls>      # play normally for up to this many rolls
    python bot.py ads <max_ads>    # ignore rolling/building: just watch up to this many free videos in a row

For ordinary refills, the bot first looks for the VIDEO bonus icon in the right-side lobby stack using an image
template; it will not tap another icon if that match is missing or uncertain. If unavailable or on cooldown,
it falls back to the separate free-video bubble above the character. Offer popups are closed without selecting
their FREE tiles, and generic popup WATCH buttons are ignored. Separately recognized event-specific video
flows include SHOW TIME JOURNEY: its WATCH tiers are tried one at a time, and the bot proceeds only when a tap
actually opens an ad.

Requires the phone serial in `bot.py`, `adb` at `tools/platform-tools/adb.exe` (not included),
`opencv-python`, `numpy`, `rapidocr-onnxruntime`, `av`.
