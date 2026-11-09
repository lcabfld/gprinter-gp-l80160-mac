"""Render Markdown to a black-and-white image sized for the thermal printer."""
import re
import subprocess
import tempfile
from functools import lru_cache
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

FONTS = Path(__file__).with_name("fonts")
REGULAR = "Geist[wght].ttf"
ITALIC = "Geist-Italic[wght].ttf"
MONO = "GeistMono[wght].ttf"

WHITE_PAINT = re.compile(rb'''((?:fill|stroke)=)["'](?:white|#fff|#ffffff)["']''', re.I)

BODY = 24
HEADINGS = {1: 46, 2: 36, 3: 29, 4: 25, 5: 24, 6: 24}
LINE_SPACING = 1.3
BLOCK_GAP = 14
INDENT = 30
MARGIN = 6

INLINE = re.compile(
    r"(`[^`]+`|\*\*\*.+?\*\*\*|\*\*.+?\*\*|__.+?__|\*[^*\s][^*]*\*|(?<!\w)_[^_\s][^_]*_(?!\w)|\[[^\]]+\]\([^)]*\))"
)


@lru_cache(maxsize=None)
def font(size, bold=False, italic=False, mono=False):
    file = MONO if mono else ITALIC if italic else REGULAR
    face = ImageFont.truetype(FONTS / file, size)
    face.set_variation_by_axes([700 if bold else 400])
    return face


def spans(text, bold=False, italic=False):
    """Split inline Markdown into (text, bold, italic, mono) runs."""
    runs = []
    for part in INLINE.split(text):
        if not part:
            continue
        if part.startswith("`") and part.endswith("`") and len(part) > 1:
            runs.append((part[1:-1], bold, italic, True))
        elif part[:3] == "***" and len(part) > 6:
            runs += spans(part[3:-3], True, True)
        elif part[:2] in ("**", "__") and len(part) > 4:
            runs += spans(part[2:-2], True, italic)
        elif part.startswith("[") and "](" in part:
            runs += spans(part[1 : part.index("](")], bold, italic)
        elif part[0] in "*_" and part[-1] == part[0] and len(part) > 2:
            runs += spans(part[1:-1], bold, True)
        else:
            runs.append((part, bold, italic, False))
    return runs


class Page:
    def __init__(self, width):
        self.width = width
        self.y = 0
        self.texts = []
        self.lines = []

    def flow(self, text, size=BODY, left=MARGIN, bold=False, mono=False):
        """Word-wrap inline Markdown from left to the right margin."""
        right = self.width - MARGIN
        tokens = []
        for run, run_bold, italic, run_mono in spans(text, bold):
            face = font(size, run_bold, italic, mono or run_mono)
            tokens += [(word, face) for word in re.findall(r"\s+|\S+", run)]

        line, x = [], left
        for word, face in tokens:
            if word.isspace() and not line and not mono:
                continue
            if x + face.getlength(word) > right and line and not word.isspace():
                self._finish(line, size)
                line, x = [], left
            while x + face.getlength(word) > right and len(word) > 1:
                fit = len(word) - 1
                while fit > 1 and x + face.getlength(word[:fit]) > right:
                    fit -= 1
                line.append((x, word[:fit], face))
                self._finish(line, size)
                line, x, word = [], left, word[fit:]
            line.append((x, word, face))
            x += face.getlength(word)
        if line:
            self._finish(line, size)

    def _finish(self, line, size):
        baseline = self.y + size
        self.texts += [(x, baseline, word, face) for x, word, face in line]
        self.y += round(size * LINE_SPACING)

    def rule(self, height=2):
        self.lines.append((MARGIN, self.y, self.width - MARGIN, self.y + height - 1))
        self.y += height

    def render(self):
        image =Image.new("L", (self.width, max(self.y, 1) + MARGIN), 255)
        draw = ImageDraw.Draw(image)
        # Antialiased edges would dither into speckle, so draw hard dots.
        draw.fontmode = "1"
        for x, baseline, word, face in self.texts:
            draw.text((x, baseline), word, fill=0, font=face, anchor="ls")
        for box in self.lines:
            draw.rectangle(box, fill=0)
        return image


def add_caption(image, text):
    """Return the image with a line of small black text underneath it."""
    captioned = Image.new("L", (image.width, image.height + 34), 255)
    captioned.paste(image, (0, 0))
    draw = ImageDraw.Draw(captioned)
    draw.fontmode = "1"
    draw.text((image.width // 2, image.height + 25), text, fill=0, font=font(17, mono=True), anchor="ms")
    return captioned


def quick_look(svg):
    """Rasterize SVG bytes with macOS Quick Look, cropped to the artwork."""
    with tempfile.TemporaryDirectory() as folder:
        path = Path(folder, "art.svg")
        path.write_bytes(svg)
        subprocess.run(
            ["qlmanage", "-t", "-s", "4000", "-o", folder, str(path)],
            capture_output=True, timeout=30, check=True,
        )
        art = Image.open(Path(folder, "art.svg.png")).convert("RGBA")
        art.load()
    flat = Image.alpha_composite(Image.new("RGBA", art.size, "white"), art).convert("L")
    box = flat.point(lambda v: 255 if v < 200 else 0).getbbox()
    return flat.crop(box) if box else None


def render_svg(svg, width):
    # Quick Look previews anything, so check this really is an SVG first.
    if b"<svg" not in svg[:4096]:
        raise ValueError("not a valid SVG file")
    art = quick_look(svg)
    if art is None:
        # White artwork can't print on white paper, so print it black.
        art = quick_look(WHITE_PAINT.sub(rb'\1"black"', svg))
    if art is None:
        raise ValueError("SVG has nothing to print")
    height = round(art.height * width / art.width)
    return art.resize((width, height), Image.LANCZOS).point(lambda v: 255 if v > 200 else 0)


def render_markdown(text, width):
    page = Page(width)
    lines = text.replace("\t", "    ").splitlines()
    paragraph = []
    ordered = {}

    def flush():
        if paragraph:
            page.flow(" ".join(paragraph))
            page.y += BLOCK_GAP
            paragraph.clear()

    i = 0
    while i < len(lines):
        line = lines[i]
        stripped = line.strip()
        i += 1

        if stripped.startswith("```"):
            flush()
            top = page.y
            while i < len(lines) and not lines[i].strip().startswith("```"):
                page.flow(lines[i] or " ", 20, MARGIN + 12, mono=True)
                i += 1
            i += 1
            page.lines.append((MARGIN, top, MARGIN + 2, page.y))
            page.y += BLOCK_GAP
        elif not stripped:
            flush()
            ordered.clear()
        elif match := re.fullmatch(r"(#{1,6})\s+(.*?)\s*#*", stripped):
            flush()
            page.y += BLOCK_GAP // 2
            page.flow(match[2], HEADINGS[len(match[1])], bold=True)
            page.y += BLOCK_GAP // 2
        elif re.fullmatch(r"([-*_])(\s*\1){2,}", stripped):
            flush()
            page.y += BLOCK_GAP // 2
            page.rule()
            page.y += BLOCK_GAP
        elif match := re.match(r"(\s*)([-*+]|\d+[.)])\s+(.*)", line):
            flush()
            level = len(match[1]) // 2
            left = MARGIN + level * INDENT
            if match[2][0].isdigit():
                ordered[level] = ordered.get(level, 0) + 1
                marker, hang = f"{ordered[level]}.", 34
            else:
                marker, hang = "•" if level == 0 else "–", 24
            page.texts.append((left, page.y + BODY, marker, font(BODY)))
            page.flow(match[3], left=left + hang)
            page.y += 4
            next_line = lines[i] if i < len(lines) else ""
            if not re.match(r"\s*([-*+]|\d+[.)])\s", next_line):
                page.y += BLOCK_GAP - 4
        elif stripped.startswith(">"):
            flush()
            top = page.y
            quote = []
            i -= 1
            while i < len(lines) and lines[i].strip().startswith(">"):
                quote.append(lines[i].strip().lstrip(">").strip())
                i += 1
            page.flow(f"*{' '.join(quote)}*", left=MARGIN + 18)
            page.lines.append((MARGIN, top, MARGIN + 3, page.y))
            page.y += BLOCK_GAP
        else:
            paragraph.append(stripped)
    flush()
    return page.render()
