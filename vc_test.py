"""One-off: watch every open tile on the ENDLESS REWARDS / VIDEO CRAZE grid that is currently on screen."""
import bot

bot.require_phone()
print("on grid:", bot.video_craze_screen(bot.shot()), flush=True)
print("watched something:", bot.use_video_craze(), flush=True)
