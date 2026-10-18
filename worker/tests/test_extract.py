from datetime import date

from pipeline.decide import Checks, decide
from pipeline.extract import (
    best_name_match,
    identify_college,
    name_score,
    norm_roll,
    roll_found,
    roll_fits_format,
    validity,
)
from pipeline.types import CollegeInfo, OcrLine, RegInfo

NSUT = CollegeInfo(id=1, name="Netaji Subhas University of Technology", aliases=["NSUT"], roll_regex=r"^20\d{2}U[A-Z]{2}\d{4}$")
DTU = CollegeInfo(id=2, name="Delhi Technological University", aliases=["DTU"])
DU = CollegeInfo(id=3, name="Hansraj College", aliases=["HANSRAJ COLLEGE UNIVERSITY OF DELHI"])


def L(text, y, x=300, conf=0.9, h=34):
    return OcrLine(text=text, conf=conf, box=(x, y, x + 20 * len(text), y + h))


CARD = [
    L("NETAJISUBHASUNIVERSITY OFTECHNOLOGY", 40, x=40),
    L("Name: AARAV SHARMA", 170),
    L("RollNo:2022UIC35O1", 232),          # OCR read 0 as O
    L("Father's Name: RAJESH SHARMA", 356),
    L("Valid upto: 31/07/2026", 418),
]


def test_college_identified_despite_missing_spaces():
    c, score = identify_college(CARD, [DTU, DU, NSUT])
    assert c is NSUT and score >= 85


def test_short_acronym_needs_whole_word():
    lines = [L("STUDENTUDENTITY", 10)]
    assert identify_college(lines, [DTU])[0] is None
    assert identify_college([L("DTU STUDENT CARD", 10)], [DTU])[0] is DTU


def test_name_matching():
    assert name_score("Aarav Sharma", "AARAV SHARMA") == 100
    assert name_score("Aarav Sharma", "AARAVSHARMA") == 100            # spaces dropped by OCR
    assert name_score("Aarav Sharma", "A. SHARMA") >= 85                # initial
    assert name_score("Aarav Sharma", "AARAV KUMAR SHARMA") >= 85       # extra middle name
    assert name_score("Aarav Sharma", "SHARMA") < 85                    # surname alone
    assert name_score("Aarav Sharma", "RAJESH SHARMA") < 85             # father
    score, seen = best_name_match(CARD, "Aarav Sharma", None)
    assert score == 100 and seen == "AARAV SHARMA"
    assert best_name_match(CARD, "Rajesh Sharma", None)[0] < 85         # father's line is skipped


def test_roll_matching():
    assert norm_roll("2O22 uic-35O1") == "2022UIC3501"
    assert roll_found(CARD, "2022UIC3501")[0] == "exact"
    assert roll_found([L("Roll No: 2022UC3501", 10)], "2022UIC3501")[0] == "close"   # one dropped letter
    assert roll_found([L("Roll No: 2022UC3502", 10)], "2022UIC3501")[0] == "missing"  # two differences
    assert roll_found([L("Roll No: 1234", 10)], "1235")[0] == "missing"              # short: exact only
    split = [L("Roll No: 2022UIC", 10, x=300), L("3501", 10, x=800)]
    assert roll_found(split, "2022UIC3501")[0] == "exact"
    assert roll_fits_format("2022UIC3501", NSUT.roll_regex) is True
    assert roll_fits_format("21/12345", NSUT.roll_regex) is False
    assert roll_fits_format("anything", None) is None


def test_validity_uses_label_or_session_only():
    assert validity(CARD, None)[0] == date(2026, 7, 31)
    assert validity([L("Session 2022-26", 10)], None) == (date(2026, 7, 31), 0.8, "session")
    assert validity([L("DOB: 01/02/2004", 10)], None)[0] is None       # never mistake a birth date
    assert validity([L("Valid Till", 10, x=100), L("JUN 2027", 10, x=400)], None)[0] == date(2027, 6, 28)


def checks(**over):
    base = dict(poor_image=False, card_college=NSUT, name_score=100, roll="exact", roll_format_ok=True,
                valid_until=date(2027, 7, 31), valid_conf=0.95, valid_source="label", face_found=True,
                duplicate_card=False)
    base.update(over)
    return Checks(**base)


REG = RegInfo(id="r1", name="Aarav Sharma", roll_no="2022UIC3501", college_id=1, college_email=True, reasons=[])
FEST = date(2026, 10, 24)


def test_decide_approves_clean_card():
    assert decide(REG, NSUT, checks(), FEST) == ("approved", [])
    assert decide(REG, NSUT, checks(roll="close"), FEST) == ("approved", [])


def test_decide_review_reasons():
    assert decide(REG, NSUT, checks(name_score=60), FEST) == ("review", ["name_mismatch"])
    assert decide(REG, NSUT, checks(card_college=DTU), FEST) == ("review", ["college_mismatch"])
    assert decide(REG, NSUT, checks(roll_format_ok=False), FEST) == ("review", ["roll_mismatch"])
    assert decide(REG, NSUT, checks(face_found=False, duplicate_card=True), FEST) == ("review", ["duplicate_card", "no_face"])
    dup_reg = RegInfo(**{**REG.__dict__, "reasons": ["duplicate_roll"]})
    assert decide(dup_reg, NSUT, checks(), FEST) == ("review", ["duplicate_roll"])


def test_decide_personal_email_needs_template():
    personal = RegInfo(**{**REG.__dict__, "college_email": False, "college_id": 2})
    assert decide(personal, DTU, checks(card_college=DTU), FEST) == ("review", ["no_template"])
    assert decide(personal, NSUT, checks(), FEST) == ("approved", [])


def test_decide_expiry():
    expired = dict(valid_until=date(2026, 7, 31))
    late_fest = date(2026, 11, 1)
    assert decide(REG, NSUT, checks(**expired), late_fest) == ("rejected", ["card_expired"])
    assert decide(REG, NSUT, checks(**expired, valid_conf=0.6), late_fest) == ("review", ["card_expired"])
    assert decide(REG, NSUT, checks(**expired, valid_source="session"), late_fest) == ("review", ["card_expired"])


def test_poor_image_replaces_read_failures():
    assert decide(REG, NSUT, checks(poor_image=True, name_score=40, roll="missing"), FEST) == ("review", ["poor_image"])
    assert decide(REG, NSUT, checks(poor_image=True), FEST) == ("approved", [])  # blurry but fully read: fine
