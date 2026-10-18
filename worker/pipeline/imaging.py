"""Image steps: decode, quality check, find and flatten the card, crop the face, hash."""

import io
from dataclasses import dataclass

import cv2
import imagehash
import numpy as np
from PIL import Image, ImageOps

try:  # HEIC/HEIF support (iPhone photos)
    import pillow_heif

    pillow_heif.register_heif_opener()
except ImportError:  # pragma: no cover
    pass

MAX_SIDE = 1600  # OCR doesn't need more; keeps it ~0.5 s per card on CPU


def load(data: bytes) -> np.ndarray:
    """Decode any supported photo, apply EXIF rotation, return BGR, longest side <= MAX_SIDE."""
    img = ImageOps.exif_transpose(Image.open(io.BytesIO(data))).convert("RGB")
    img.thumbnail((MAX_SIDE, MAX_SIDE))
    return cv2.cvtColor(np.asarray(img), cv2.COLOR_RGB2BGR)


@dataclass
class Quality:
    long_side: int
    sharpness: float  # variance of the Laplacian; low = blurry

    def poor(self, min_side: int = 700, min_sharpness: float = 40.0) -> bool:
        return self.long_side < min_side or self.sharpness < min_sharpness


def quality(bgr: np.ndarray, original_long_side: int) -> Quality:
    gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
    return Quality(long_side=original_long_side, sharpness=float(cv2.Laplacian(gray, cv2.CV_64F).var()))


def original_long_side(data: bytes) -> int:
    w, h = ImageOps.exif_transpose(Image.open(io.BytesIO(data))).size
    return max(w, h)


def _order(pts: np.ndarray) -> np.ndarray:
    s, d = pts.sum(1), np.diff(pts, axis=1).ravel()
    return np.array([pts[s.argmin()], pts[d.argmin()], pts[s.argmax()], pts[d.argmax()]], dtype=np.float32)


def find_card(bgr: np.ndarray) -> tuple[np.ndarray, bool]:
    """Flatten the card if a clear four-sided outline covers >= 20% of the photo; else return the photo."""
    h, w = bgr.shape[:2]
    gray = cv2.GaussianBlur(cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY), (5, 5), 0)
    edges = cv2.dilate(cv2.Canny(gray, 50, 150), np.ones((3, 3), np.uint8))
    contours, _ = cv2.findContours(edges, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    for c in sorted(contours, key=cv2.contourArea, reverse=True)[:5]:
        if cv2.contourArea(c) < 0.2 * w * h:
            break
        approx = cv2.approxPolyDP(c, 0.02 * cv2.arcLength(c, True), True)
        if len(approx) != 4:
            continue
        tl, tr, br, bl = _order(approx.reshape(4, 2).astype(np.float32))
        W = int(max(np.linalg.norm(tr - tl), np.linalg.norm(br - bl)))
        H = int(max(np.linalg.norm(bl - tl), np.linalg.norm(br - tr)))
        if min(W, H) < 200:
            continue
        # Only trust outlines shaped like an ID card (ISO ID-1 is 1.586:1), landscape or portrait.
        # Anything else is usually part of the card, e.g. the white area under a coloured header.
        ratio = max(W, H) / min(W, H)
        if not 1.35 <= ratio <= 1.85:
            continue
        M = cv2.getPerspectiveTransform(np.array([tl, tr, br, bl]), np.float32([[0, 0], [W, 0], [W, H], [0, H]]))
        return cv2.warpPerspective(bgr, M, (W, H)), True
    return bgr, False


_face = cv2.CascadeClassifier(cv2.data.haarcascades + "haarcascade_frontalface_default.xml")
_clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))


def crop_face(bgr: np.ndarray, size: int = 320) -> bytes | None:
    """JPEG of the largest face on the card with some margin, or None if no face is found."""
    # Local contrast (CLAHE) copes with glare and dark photos better than global equalisation.
    gray = _clahe.apply(cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY))
    h, w = gray.shape
    faces = _face.detectMultiScale(gray, scaleFactor=1.05, minNeighbors=4, minSize=(max(40, w // 25),) * 2)
    if len(faces) == 0:
        return None
    x, y, fw, fh = max(faces, key=lambda f: f[2] * f[3])
    m = int(0.45 * max(fw, fh))
    x0, y0, x1, y1 = max(0, x - m), max(0, y - m), min(w, x + fw + m), min(h, y + fh + int(m * 1.3))
    crop = bgr[y0:y1, x0:x1]
    scale = size / max(crop.shape[:2])
    crop = cv2.resize(crop, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)
    ok, buf = cv2.imencode(".jpg", crop, [cv2.IMWRITE_JPEG_QUALITY, 88])
    return buf.tobytes() if ok else None


def phash_face(face_jpeg: bytes) -> int:
    """64-bit perceptual hash of the face crop, as a signed int (fits Postgres bigint).

    Hashing the whole card doesn't work: cards from one college share a layout, so different
    students' cards hash the same. The portrait is what differs between students, and what
    stays the same when someone reuses a card photo.
    """
    h = imagehash.phash(Image.open(io.BytesIO(face_jpeg)).convert("L"))
    v = int(str(h), 16)
    return v - (1 << 64) if v >= (1 << 63) else v
