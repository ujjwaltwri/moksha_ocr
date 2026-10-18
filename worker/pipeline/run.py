"""Run every image and OCR step on one card. No database or storage here; the worker job does I/O."""

import time
from dataclasses import dataclass

from . import extract, imaging, ocr
from .decide import Checks
from .types import CollegeInfo, RegInfo


@dataclass
class CardResult:
    checks: Checks            # duplicate_card is filled in later by the job (needs the database)
    ocr: dict                 # stored in registrations.ocr for reviewers
    face_jpeg: bytes | None
    phash: int | None         # of the face crop; None when no face was found


def run(data: bytes, reg: RegInfo, chosen: CollegeInfo | None, colleges: list[CollegeInfo]) -> CardResult:
    t0 = time.monotonic()
    long_side = imaging.original_long_side(data)
    bgr = imaging.load(data)
    q = imaging.quality(bgr, long_side)
    card, card_found = imaging.find_card(bgr)

    lines = ocr.read(card)
    if len(lines) < 3 and card_found:
        # The outline we flattened may have been wrong (a photo frame, a table edge); try the whole photo.
        alt = ocr.read(bgr)
        if len(alt) > len(lines):
            card, card_found, lines = bgr, False, alt

    template = chosen.template if chosen else None
    card_college, college_score = extract.identify_college(lines, colleges)
    name_score, name_seen = extract.best_name_match(lines, reg.name, template)
    roll, roll_seen = extract.roll_found(lines, reg.roll_no)
    roll_format_ok = extract.roll_fits_format(reg.roll_no, chosen.roll_regex if chosen else None)
    valid_until, valid_conf, valid_source = extract.validity(lines, template)
    face = imaging.crop_face(card) or (imaging.crop_face(bgr) if card_found else None)

    checks = Checks(
        poor_image=q.poor(),
        card_college=card_college,
        name_score=name_score,
        roll=roll,
        roll_format_ok=roll_format_ok,
        valid_until=valid_until,
        valid_conf=valid_conf,
        valid_source=valid_source,
        face_found=face is not None,
        duplicate_card=False,
    )
    return CardResult(
        checks=checks,
        ocr={
            "lines": [{"text": l.text, "conf": round(l.conf, 3), "box": [round(v) for v in l.box]} for l in lines],
            "college": {"id": card_college.id if card_college else None, "score": round(college_score, 1)},
            "name": {"score": name_score, "seen": name_seen},
            "roll": {"match": roll, "seen": roll_seen, "format_ok": roll_format_ok},
            "valid_until": {"date": valid_until.isoformat() if valid_until else None,
                            "conf": round(valid_conf, 3), "source": valid_source},
            "image": {"long_side": q.long_side, "sharpness": round(q.sharpness, 1), "card_found": card_found},
            "face_found": face is not None,
            "ms": round((time.monotonic() - t0) * 1000),
        },
        face_jpeg=face,
        phash=imaging.phash_face(face) if face else None,
    )
