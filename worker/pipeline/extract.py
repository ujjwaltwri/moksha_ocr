"""Turn OCR lines into fields, and compare them with what the student typed.

Pure functions only (no OCR, no I/O) so they're easy to test and tune.
"""

import re
from datetime import date

from rapidfuzz import fuzz

from .types import CollegeInfo, OcrLine

DEFAULT_LABELS = {
    "name": ["Name", "Student Name", "Name of Student"],
    "roll": ["Roll No", "Roll Number", "Enrolment No", "Enrollment No", "Enrolment Number", "Enrollment Number",
             "Admission No", "Registration No", "Reg No", "Student ID", "ID No", "University Roll No"],
    "valid": ["Valid Upto", "Valid Up To", "Valid Till", "Valid Until", "Validity", "Valid Thru", "Expiry", "Date of Expiry"],
}
# Lines starting with these are about someone else, never the student's name.
NOT_STUDENT = ("FATHER", "MOTHER", "GUARDIAN", "PARENT", "PRINCIPAL", "DEAN", "REGISTRAR", "DIRECTOR", "HOD")

MONTHS = {m: i for i, m in enumerate(
    ["JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"], start=1)}


# ---------- text helpers ----------

def clean(s: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^A-Za-z0-9/.:\- ]", " ", s)).strip().upper()


def norm_roll(s: str) -> str:
    """Same normalisation as the API, plus fixing common OCR letter/digit swaps inside digit runs."""
    s = re.sub(r"[\s\-]+", "", s).upper()

    def fix(m: re.Match) -> str:
        return m.group(0).translate(str.maketrans({"O": "0", "I": "1", "L": "1", "S": "5", "B": "8", "Z": "2"}))

    # Only touch letters sandwiched between digits, e.g. 2O22 -> 2022, 35O1 -> 3501.
    return re.sub(r"(?<=\d)[OILSBZ]+(?=\d)", fix, s)


def strip_label(text: str, labels: list[str]) -> tuple[str | None, str]:
    """If `text` starts with one of `labels`, return (label, rest of the line)."""
    t = clean(text)
    for label in sorted(labels, key=len, reverse=True):
        lab = clean(label)
        head = t[: len(lab) + 2]
        if t.startswith(lab) or (len(lab) >= 6 and fuzz.ratio(head[: len(lab)], lab) >= 85):
            rest = t[len(lab):].lstrip(" .:-")
            return label, rest
    return None, t


# ---------- college ----------

def identify_college(lines: list[OcrLine], colleges: list[CollegeInfo]) -> tuple[CollegeInfo | None, float]:
    """Best-matching college by name/aliases anywhere on the card."""
    text = " ".join(clean(l.text) for l in lines)
    best, best_score = None, 0.0
    for c in colleges:
        for name in [c.name, *c.aliases]:
            n = clean(name)
            if len(n) < 3:
                continue
            score = fuzz.partial_ratio(n, text) if len(n) >= 8 else (100.0 if re.search(rf"\b{re.escape(n)}\b", text) else 0.0)
            if score > best_score:
                best, best_score = c, score
    return (best, best_score) if best_score >= 85 else (None, best_score)


# ---------- labelled fields ----------

def value_for_label(lines: list[OcrLine], labels: list[str]) -> tuple[str | None, float]:
    """Text after a label on the same line, else the nearest line to its right, else just below."""
    for i, line in enumerate(lines):
        label, rest = strip_label(line.text, labels)
        if label is None:
            continue
        if len(rest) >= 2:
            return rest, line.conf
        # Value is a separate OCR box: same row to the right first, then directly below.
        right = [o for j, o in enumerate(lines) if j != i and abs(o.cy - line.cy) < max(line.h, o.h) * 0.6 and o.box[0] > line.box[0]]
        if right:
            o = min(right, key=lambda o: o.box[0])
            return clean(o.text).lstrip(" .:-"), o.conf
        below = [o for j, o in enumerate(lines) if j != i and 0 < o.cy - line.cy < line.h * 2.5 and o.box[0] < line.box[2]]
        if below:
            o = min(below, key=lambda o: o.cy)
            return clean(o.text).lstrip(" .:-"), o.conf
    return None, 0.0


def labels_for(template: dict | None, field: str) -> list[str]:
    extra = ((template or {}).get("labels") or {}).get(field) or []
    return [*extra, *DEFAULT_LABELS[field]]


# ---------- name ----------

def _tok(s: str) -> list[str]:
    return [t for t in re.split(r"[^A-Z]+", s.upper()) if t]


def _covered(a: list[str], b: list[str]) -> float:
    """Share of tokens in `a` that appear (fuzzily, or as an initial) in `b`."""
    if not a:
        return 0.0
    hit = 0
    for t in a:
        for u in b:
            if (len(t) == 1 and u.startswith(t)) or (len(u) == 1 and t.startswith(u)) or fuzz.ratio(t, u) >= 85:
                hit += 1
                break
    return hit / len(a)


def name_score(form_name: str, candidate: str) -> float:
    """100 when every word of the form name is on the card line and the line isn't mostly other words.

    Allows initials and a missing/extra middle name. A line with only the surname scores low.
    """
    f, c = _tok(form_name), _tok(candidate)
    if not f or not c:
        return 0.0
    cov_f, cov_c = _covered(f, c), _covered(c, f)
    return round(100 * min(cov_f, max(cov_c, 0.5) + 0.5), 1) if cov_f >= 0.5 else round(100 * cov_f * 0.5, 1)


def best_name_match(lines: list[OcrLine], form_name: str, template: dict | None) -> tuple[float, str | None]:
    candidates: list[str] = []
    labelled, _ = value_for_label(lines, labels_for(template, "name"))
    if labelled:
        candidates.append(labelled)
    for line in lines:
        t = clean(line.text)
        if t.startswith(NOT_STUDENT):
            continue
        _, rest = strip_label(t, labels_for(template, "name"))
        candidates.append(rest)
    best, best_text = 0.0, None
    for cand in candidates:
        s = name_score(form_name, cand)
        if s > best:
            best, best_text = s, cand
    return best, best_text


# ---------- roll number ----------

def roll_found(lines: list[OcrLine], form_roll: str) -> tuple[bool, str | None]:
    """Is the roll number the student typed printed on the card?"""
    target = norm_roll(form_roll)
    if len(target) < 4:
        return False, None
    for line in lines:
        t = norm_roll(clean(line.text))
        if target in t:
            return True, target
    # Number split across two OCR boxes on the same row.
    joined = norm_roll("".join(clean(l.text) for l in sorted(lines, key=lambda l: (round(l.cy / max(l.h, 1)), l.box[0]))))
    return (target in joined), (target if target in joined else None)


def roll_fits_format(roll: str, regex: str | None) -> bool | None:
    if not regex:
        return None
    return re.fullmatch(regex, norm_roll(roll)) is not None


# ---------- validity date ----------

def parse_date(s: str) -> date | None:
    s = clean(s)
    m = re.search(r"\b(\d{1,2})[/.\-](\d{1,2})[/.\-](\d{2,4})\b", s)
    if m:
        d, mo, y = (int(x) for x in m.groups())
        y = y + 2000 if y < 100 else y
        try:
            return date(y, mo, d)
        except ValueError:
            return None
    m = re.search(r"\b([A-Z]{3})[A-Z]*[ .\-,]*(\d{4})\b", s)
    if m and m.group(1) in MONTHS:
        mo, y = MONTHS[m.group(1)], int(m.group(2))
        return date(y, mo, 28)
    m = re.search(r"\b(20\d{2})\b", s)
    if m:
        return date(int(m.group(1)), 12, 31)
    return None


def session_end(lines: list[OcrLine]) -> date | None:
    """Course session like 2022-26 or 2022-2026 -> valid until 31 July of the end year."""
    for line in lines:
        m = re.search(r"\b(20\d{2})\s*[-–/]\s*(20)?(\d{2})\b", clean(line.text))
        if m:
            start, end = int(m.group(1)), 2000 + int(m.group(3))
            if 0 < end - start <= 6:
                return date(end, 7, 31)
    return None


def validity(lines: list[OcrLine], template: dict | None) -> tuple[date | None, float, str]:
    """(valid-until date, OCR confidence, source). Only uses labelled dates or a course session,
    never a random date on the card (that might be a date of birth)."""
    text, conf = value_for_label(lines, labels_for(template, "valid"))
    if text:
        d = parse_date(text)
        if d:
            return d, conf, "label"
    d = session_end(lines)
    if d:
        return d, 0.8, "session"
    return None, 0.0, "none"
