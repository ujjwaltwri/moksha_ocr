from dataclasses import dataclass, field


@dataclass
class OcrLine:
    text: str
    conf: float
    box: tuple[float, float, float, float]  # x0, y0, x1, y1 in card pixels

    @property
    def cx(self) -> float:
        return (self.box[0] + self.box[2]) / 2

    @property
    def cy(self) -> float:
        return (self.box[1] + self.box[3]) / 2

    @property
    def h(self) -> float:
        return self.box[3] - self.box[1]


@dataclass
class CollegeInfo:
    id: int
    name: str
    aliases: list[str] = field(default_factory=list)
    email_domains: list[str] = field(default_factory=list)
    roll_regex: str | None = None
    template: dict | None = None
    allowed: bool = True

    @property
    def has_template(self) -> bool:
        return bool(self.roll_regex)


@dataclass
class RegInfo:
    id: str
    name: str
    roll_no: str              # already normalised by the API
    college_id: int | None
    college_email: bool
    reasons: list[str]        # set at registration time (duplicate_roll, other_college)
