"""Generates a simple branded placeholder cover (title + author on a soft
gradient, matching the app's pastel theme) for novels whose source page
has no cover image -- better than shipping an EPUB with a blank cover.
"""
import io
import textwrap

from PIL import Image, ImageDraw, ImageFont

WIDTH, HEIGHT = 600, 800
TOP_COLOR = (91, 155, 209)     # #5B9BD1, the app's blue accent
BOTTOM_COLOR = (244, 169, 200)  # #F4A9C8, the app's pink accent


def _load_font(size, bold=False):
    candidates = (
        ['segoeuib.ttf', 'arialbd.ttf'] if bold
        else ['segoeui.ttf', 'arial.ttf'])
    for name in candidates:
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    return ImageFont.load_default()


def _draw_gradient(draw):
    for y in range(HEIGHT):
        t = y / HEIGHT
        color = tuple(
            int(TOP_COLOR[i] + (BOTTOM_COLOR[i] - TOP_COLOR[i]) * t)
            for i in range(3))
        draw.line([(0, y), (WIDTH, y)], fill=color)


def _draw_centered_text(draw, text, font, y, fill, stroke_fill=None):
    bbox = draw.textbbox((0, 0), text, font=font)
    width = bbox[2] - bbox[0]
    kwargs = {}
    if stroke_fill is not None:
        kwargs = {'stroke_width': 2, 'stroke_fill': stroke_fill}
    draw.text(((WIDTH - width) // 2, y), text, font=font, fill=fill, **kwargs)


def generate_cover_bytes(title, author=''):
    image = Image.new('RGB', (WIDTH, HEIGHT), BOTTOM_COLOR)
    draw = ImageDraw.Draw(image)
    _draw_gradient(draw)

    title_font = _load_font(46, bold=True)
    author_font = _load_font(26)

    wrapped_title = textwrap.wrap(title or 'Untitled', width=16) or ['Untitled']
    line_height = 58
    block_height = len(wrapped_title) * line_height
    y = (HEIGHT - block_height) // 2 - 30
    for line in wrapped_title:
        _draw_centered_text(
            draw, line, title_font, y, fill='white',
            stroke_fill=(45, 35, 55))
        y += line_height

    if author:
        _draw_centered_text(
            draw, author, author_font, y + 28, fill='white')

    buffer = io.BytesIO()
    image.save(buffer, format='JPEG', quality=88)
    return buffer.getvalue()
