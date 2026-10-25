# Dice Dreams bot

ADB (USB) player for the mobile game Dice Dreams. It rolls the dice at the multiplier the "MAX xN" bubble
names (or whatever is already set, if that bubble isn't shown), upgrades the kingdom one building at a time
(saves up for the whole front card instead of buying single steps), watches free videos once money and
energy both run out (until any energy is back, no cap on how many), and handles the pop-ups, mini-games
(sling, steal, fight, pinball) and the kingdom-restored share screen (story only, never the feed).

Never presses a real-money purchase button (payment screens are closed with X / BACK).

    python bot.py <max_rolls>      # play normally for up to this many rolls
    python bot.py ads <max_ads>    # ignore rolling/building: just watch up to this many free videos in a row
    python bot.py ads hammer       # watch lobby/event videos only until the golden-hammer discount appears
    python bot.py sale <max_rolls> # drain stored energy, wait for the golden-hammer VIDEO, upgrade with coins, then stop

For ordinary refills, the bot first looks for the VIDEO bonus icon in the right-side lobby stack using an image
template; it will not tap another icon if that match is missing or uncertain. If unavailable or on cooldown,
it falls back to the separate free-video bubble above the character. Offer popups are closed without selecting
their FREE tiles, and generic popup WATCH buttons are ignored. Separately recognized event-specific video
flows include SHOW TIME JOURNEY: its WATCH tiers are tried one at a time, and the bot proceeds only when a tap
actually opens an ad.

Building scans begin at the left edge, inspect the three visible card slots (price/upgrade button present means
unfinished; no upgrade button means complete), then advance in 500-pixel steps to preserve more overlap between
scans. The bot skips cards whose next upgrade costs more than the current coins and upgrades an affordable
card it finds, rather than waiting for the leftmost card. Each scroll settles before OCR; if kingdom
progress still shows unfinished steps after a failed scan, the next attempt starts over at the first card and
TRAIL is deferred. If no upgrade is affordable, the bot waits until it has enough coins for the cheapest known
next step before reopening the build panel. After a build scan, it verifies that the upgrade panel actually
closed and retries the scene/hammer toggle if it remains open. The TRAIL flow also leaves the event if its
token count has not advanced for two minutes, rather than staying on a stalled screen indefinitely.

Requires the phone serial in `bot.py`, `adb` at `tools/platform-tools/adb.exe` (not included),
`opencv-python`, `numpy`, `rapidocr-onnxruntime`, `av`.

For portrait and landscape ads, the bot immediately taps a recognized screen-relative corner X before checking
playback timers, then checks for a recognized SKIP/CLOSE label (including "Skip to Google Play") or a learned
exit glyph; it never guesses a tap location.
