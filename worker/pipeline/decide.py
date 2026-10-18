"""Verdict rules (build spec, "Decision rules"). Approve only clean cases; almost never reject."""

from dataclasses import dataclass
from datetime import date

from .types import CollegeInfo, RegInfo

NAME_MIN = 85.0


@dataclass
class Checks:
    poor_image: bool
    card_college: CollegeInfo | None   # college identified on the card
    name_score: float
    roll: str                          # exact | close | missing
    roll_format_ok: bool | None        # None = college has no roll rule
    valid_until: date | None
    valid_conf: float
    valid_source: str                  # label | session | none
    face_found: bool
    duplicate_card: bool


def decide(reg: RegInfo, chosen: CollegeInfo | None, c: Checks, fest_day: date) -> tuple[str, list[str]]:
    """Returns (status, reasons). Reasons already on the registration are kept."""
    reasons = set(reg.reasons)

    # Clear rejections: card expired (read confidently from a labelled date) or college not invited.
    if chosen is not None and not chosen.allowed:
        return "rejected", sorted(reasons | {"college_not_allowed"})
    if c.valid_until and c.valid_source == "label" and c.valid_conf >= 0.8 and c.valid_until < fest_day:
        return "rejected", sorted(reasons | {"card_expired"})

    if chosen is not None and (c.card_college is None or c.card_college.id != chosen.id):
        reasons.add("college_mismatch")
    if c.name_score < NAME_MIN:
        reasons.add("name_mismatch")
    if c.roll == "missing" or c.roll_format_ok is False:
        reasons.add("roll_mismatch")
    if not c.face_found:
        reasons.add("no_face")
    if c.duplicate_card:
        reasons.add("duplicate_card")
    if chosen is not None and not reg.college_email and not chosen.has_template:
        reasons.add("no_template")
    if c.valid_until and c.valid_until < fest_day:  # expired but not read confidently: a person decides
        reasons.add("card_expired")

    # A bad photo explains failed reads: ask for a better photo instead of listing every mismatch.
    unreadable = {"name_mismatch", "roll_mismatch", "college_mismatch", "no_face"}
    if c.poor_image and reasons & unreadable:
        reasons -= unreadable
        reasons.add("poor_image")

    return ("review" if reasons else "approved"), sorted(reasons)
