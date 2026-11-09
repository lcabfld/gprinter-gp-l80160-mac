"""Draw the app icon: the Apple printer emoji, with standard macOS icon margins."""
import sys

from PIL import Image, ImageDraw, ImageFont

EMOJI_FONT = "/System/Library/Fonts/Apple Color Emoji.ttc"
EMOJI = "\U0001F5A8️"
STRIKE = 160  # the font's largest built-in bitmap size
CANVAS = 1024
ART = 840

glyph = Image.new("RGBA", (STRIKE * 2, STRIKE * 2), (0, 0, 0, 0))
ImageDraw.Draw(glyph).text(
    (STRIKE // 2, STRIKE // 2), EMOJI, font=ImageFont.truetype(EMOJI_FONT, STRIKE), embedded_color=True
)
glyph = glyph.crop(glyph.getbbox())

scale = ART / max(glyph.size)
glyph = glyph.resize((round(glyph.width * scale), round(glyph.height * scale)), Image.LANCZOS)

icon = Image.new("RGBA", (CANVAS, CANVAS), (0, 0, 0, 0))
icon.alpha_composite(glyph, ((CANVAS - glyph.width) // 2, (CANVAS - glyph.height) // 2))
icon.save(sys.argv[1])
