import re
from typing import Literal

from pydantic import BaseModel, EmailStr, Field, field_validator, model_validator

ALLOWED_TYPES = {"image/jpeg": "jpg", "image/png": "png", "image/heic": "heic", "image/heif": "heic"}


def normalize_roll(roll: str) -> str:
    """Uppercase and drop spaces and dashes. Slashes stay: some DU numbers use them."""
    return re.sub(r"[\s\-]+", "", roll).upper()


def normalize_phone(phone: str) -> str:
    digits = re.sub(r"\D", "", phone)
    if len(digits) == 12 and digits.startswith("91"):
        digits = digits[2:]
    if not re.fullmatch(r"[6-9]\d{9}", digits):
        raise ValueError("enter a 10-digit Indian mobile number")
    return digits


def validate_upload_key(v: str) -> str:
    if not re.fullmatch(r"id-cards/[0-9a-f-]{36}\.(jpg|png|heic)", v):
        raise ValueError("invalid upload key")
    return v


class ReuploadIn(BaseModel):
    id_image_key: str

    @field_validator("id_image_key")
    @classmethod
    def key_shape(cls, v: str) -> str:
        return validate_upload_key(v)


class CollegeOut(BaseModel):
    id: int
    name: str


class PresignIn(BaseModel):
    content_type: str
    size: int = Field(gt=0)

    @field_validator("content_type")
    @classmethod
    def known_type(cls, v: str) -> str:
        v = v.lower()
        if v not in ALLOWED_TYPES:
            raise ValueError("upload a JPG, PNG or HEIC photo")
        return v


class PresignOut(BaseModel):
    url: str
    fields: dict
    key: str
    expires_in: int


class RegistrationIn(BaseModel):
    name: str = Field(min_length=2, max_length=120)
    college_id: int | None = None
    college_other: str | None = Field(default=None, max_length=200)
    roll_no: str = Field(min_length=2, max_length=40)
    course: str | None = Field(default=None, max_length=120)
    email: EmailStr
    phone: str | None = None
    id_image_key: str
    consent_entry: Literal[True]          # required: entry can't happen without it
    consent_dataset: bool = False         # optional, unticked by default
    consent_version: str
    captcha_token: str | None = None

    @field_validator("name", "college_other", "course")
    @classmethod
    def strip(cls, v: str | None) -> str | None:
        if v is None:
            return v
        v = " ".join(v.split())
        return v or None

    @field_validator("roll_no")
    @classmethod
    def roll(cls, v: str) -> str:
        v = normalize_roll(v)
        if len(v) < 2:
            raise ValueError("enter your roll or enrolment number")
        return v

    @field_validator("phone")
    @classmethod
    def phone_ok(cls, v: str | None) -> str | None:
        return normalize_phone(v) if v else None

    @field_validator("id_image_key")
    @classmethod
    def key_shape(cls, v: str) -> str:
        return validate_upload_key(v)

    @model_validator(mode="after")
    def one_college(self) -> "RegistrationIn":
        if (self.college_id is None) == (self.college_other is None):
            raise ValueError("pick your college from the list, or choose Other and type its name")
        return self


class RegistrationOut(BaseModel):
    id: str
    status: str
    status_url: str
    status_token: str


# Plain-language explanations shown on the student's status page.
REASON_TEXT = {
    "poor_image": "Your ID card photo is blurry or too small. Please upload a clearer photo.",
    "college_mismatch": "The college on your card doesn't match the one you picked. A volunteer will check it.",
    "name_mismatch": "The name on your card doesn't match the form. A volunteer will check it.",
    "roll_mismatch": "The roll number on your card doesn't match the form. A volunteer will check it.",
    "no_face": "We couldn't find the photo on your ID card. Please upload a photo of the front side.",
    "duplicate_roll": "This roll number is already registered. A volunteer will check it.",
    "duplicate_card": "This ID card photo was already used. A volunteer will check it.",
    "no_template": "We don't know your college's card format yet. A volunteer will check it.",
    "other_college": "Your college isn't on our list yet. A volunteer will check it.",
    "college_not_allowed": "Your college isn't part of this year's Moksha.",
    "card_expired": "Your ID card has expired.",
}

STATUS_TEXT = {
    "pending": "Received. We're checking your ID card.",
    "processing": "We're checking your ID card.",
    "review": "A volunteer is reviewing your registration. This usually takes under 24 hours.",
    "approved": "Approved! Your entry pass has been emailed to you.",
    "rejected": "Your registration wasn't approved.",
}


class StatusOut(BaseModel):
    name: str
    college: str
    status: str
    message: str
    reasons: list[str]
    can_reupload: bool
    qr_token: str | None = None
