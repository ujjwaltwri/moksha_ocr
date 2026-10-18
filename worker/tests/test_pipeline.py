"""Real OCR on synthetic cards, photographed at an angle on a table."""

from datetime import date

import pytest

from pipeline.decide import decide
from pipeline.run import run
from pipeline.types import CollegeInfo, RegInfo
from tests.cards import card, jpeg, photographed

NSUT = CollegeInfo(id=1, name="Netaji Subhas University of Technology", aliases=["NSUT"],
                   email_domains=["nsut.ac.in"], roll_regex=r"^20\d{2}U[A-Z]{2}\d{4}$")
DTU = CollegeInfo(id=2, name="Delhi Technological University", aliases=["DTU"])
COLLEGES = [NSUT, DTU]
FEST = date(2026, 10, 24)


def reg(**over):
    base = dict(id="r", name="Aarav Sharma", roll_no="2022UIC3501", college_id=1, college_email=True, reasons=[])
    base.update(over)
    return RegInfo(**base)


def verdict(image_bytes, r=None, chosen=NSUT):
    r = r or reg()
    res = run(image_bytes, r, chosen, COLLEGES)
    return decide(r, chosen, res.checks, FEST), res


def test_clean_card_photo_is_approved():
    (status, reasons), res = verdict(jpeg(photographed(card())))
    assert (status, reasons) == ("approved", []), res.ocr
    assert res.face_jpeg and res.face_jpeg[:2] == b"\xff\xd8"
    assert res.ocr["college"]["id"] == 1
    assert res.ocr["ms"] < 5000


def test_straight_scan_is_approved():
    assert verdict(jpeg(card()))[0] == ("approved", [])


def test_wrong_name_goes_to_review():
    assert verdict(jpeg(photographed(card())), reg(name="Rohan Verma"))[0] == ("review", ["name_mismatch"])


def test_wrong_roll_goes_to_review():
    assert verdict(jpeg(photographed(card())), reg(roll_no="2022UIC9999"))[0] == ("review", ["roll_mismatch"])


def test_card_from_another_college_goes_to_review():
    img = jpeg(photographed(card(college="DELHI TECHNOLOGICAL UNIVERSITY", accent=(140, 20, 30))))
    (status, reasons), res = verdict(img)
    assert status == "review" and "college_mismatch" in reasons
    assert res.ocr["college"]["id"] == 2


def test_no_photo_on_card():
    assert verdict(jpeg(photographed(card(face=False))))[0] == ("review", ["no_face"])


def test_expired_card_is_rejected():
    assert verdict(jpeg(card(valid="30/06/2026")))[0] == ("rejected", ["card_expired"])


def test_blurry_small_photo_asks_for_reupload():
    img = jpeg(photographed(card(), blur=6, scale=0.4), quality=60)
    (status, reasons), res = verdict(img)
    assert (status, reasons) == ("review", ["poor_image"]), res.ocr


def _dist(x, y):
    return bin((x ^ y) & (2**64 - 1)).count("1")


def test_face_hash_matches_same_card_photographed_differently():
    a = run(jpeg(photographed(card())), reg(), NSUT, COLLEGES).phash
    a2 = run(jpeg(photographed(card(), tilt=False), quality=70), reg(), NSUT, COLLEGES).phash
    assert -(2**63) <= a < 2**63
    assert _dist(a, a2) <= 6, _dist(a, a2)


def test_face_hash_differs_between_people():
    a = run(jpeg(card(person=0)), reg(), NSUT, COLLEGES).phash
    b = run(jpeg(card(person=1)), reg(), NSUT, COLLEGES).phash
    assert b is not None and _dist(a, b) > 10, _dist(a, b)


def test_no_face_no_hash():
    assert run(jpeg(card(face=False)), reg(), NSUT, COLLEGES).phash is None
