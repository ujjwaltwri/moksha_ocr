"""Synthetic ID cards for tests. The portrait is scikit-image's public-domain NASA astronaut photo."""

import io

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont, ImageOps

FONT = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
FONT_BOLD = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"


def _font(size, bold=False):
    try:
        return ImageFont.truetype(FONT_BOLD if bold else FONT, size)
    except OSError:  # pragma: no cover
        return ImageFont.load_default()


def portrait(person: int = 0) -> Image.Image:
    """Head and shoulders. Different `person` values give portraits that hash as different people
    (mirrored, shifted and rotated variants of the one public-domain photo we have)."""
    from skimage import data

    img = Image.fromarray(data.astronaut())
    dx = [0, 40, -30, 20, -45, 55][person % 6]
    p = img.crop((130 + dx, 10, 330 + dx, 250))
    if person % 2:
        p = ImageOps.mirror(p)
    if person >= 2:
        p = p.rotate([0, 0, 8, -8, 12, -12][person % 6], fillcolor=(200, 200, 200))
    return p


def card(
    college="NETAJI SUBHAS UNIVERSITY OF TECHNOLOGY",
    name="AARAV SHARMA",
    roll="2022UIC3501",
    valid="31/07/2027",
    course="B.Tech ICE",
    father="RAJESH SHARMA",
    face=True,
    person=0,
    accent=(20, 60, 140),
) -> Image.Image:
    img = Image.new("RGB", (1012, 638), "white")
    d = ImageDraw.Draw(img)
    d.rectangle([0, 0, 1012, 110], fill=accent)
    d.text((40, 32), college, fill="white", font=_font(36, bold=True))
    if face:
        img.paste(portrait(person).resize((200, 240)), (50, 160))
    else:
        d.rectangle([50, 160, 250, 400], outline="gray", width=3)
    y = 170
    for label, value in [("Name", name), ("Roll No", roll), ("Course", course), ("Father's Name", father),
                         ("Valid upto", valid)]:
        if value:
            d.text((300, y), f"{label}: {value}", fill="black", font=_font(32))
            y += 62
    d.rectangle([0, 600, 1012, 638], fill=accent)
    return img


def photographed(c: Image.Image, blur=0.0, scale=1.0, tilt=True) -> Image.Image:
    """The card lying on a dark table, photographed at a slight angle."""
    bg = np.full((1200, 1600, 3), (40, 45, 50), np.uint8)
    noise = np.random.default_rng(0).integers(0, 18, bg.shape, dtype=np.uint8)
    bg = cv2.add(bg, noise)
    src = np.float32([[0, 0], [c.width, 0], [c.width, c.height], [0, c.height]])
    dst = np.float32([[260, 230], [1330, 200], [1360, 900], [230, 880]]) if tilt else \
        np.float32([[290, 280], [1302, 280], [1302, 918], [290, 918]])
    M = cv2.getPerspectiveTransform(src, dst)
    warped = cv2.warpPerspective(np.asarray(c)[:, :, ::-1], M, (1600, 1200))
    mask = cv2.warpPerspective(np.full((c.height, c.width), 255, np.uint8), M, (1600, 1200))
    bg[mask > 0] = warped[mask > 0]
    out = Image.fromarray(bg[:, :, ::-1])
    if blur:
        out = out.filter(ImageFilter.GaussianBlur(blur))
    if scale != 1.0:
        out = out.resize((int(out.width * scale), int(out.height * scale)))
    return out


def jpeg(img: Image.Image, quality=90) -> bytes:
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=quality)
    return buf.getvalue()
