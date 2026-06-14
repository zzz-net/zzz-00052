from dataclasses import dataclass, field, asdict
from datetime import date, datetime
from typing import Optional, List
import uuid


STATUS_PENDING = "待执行"
STATUS_COMPLETED = "已完成"
STATUS_REVIEWING = "待复核"
STATUS_ARCHIVED = "归档"
STATUS_CANCELLED = "取消"

STATUS_FLOW = [STATUS_PENDING, STATUS_COMPLETED, STATUS_REVIEWING, STATUS_ARCHIVED]

ROLE_OPERATOR = "操作员"
ROLE_REVIEWER = "复核员"


def _today_str() -> str:
    return date.today().isoformat()


def _new_id() -> str:
    return uuid.uuid4().hex[:12]


@dataclass
class User:
    username: str
    role: str

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "User":
        return cls(**d)


@dataclass
class Instrument:
    id: str = field(default_factory=_new_id)
    code: str = ""
    name: str = ""
    model: str = ""
    manufacturer: str = ""
    location: str = ""
    cycle_days: int = 365
    last_calibration_date: Optional[str] = None
    owner: str = ""
    remark: str = ""
    created_at: str = field(default_factory=_today_str)
    is_active: bool = True

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "Instrument":
        return cls(**d)


@dataclass
class CalibrationRecord:
    id: str = field(default_factory=_new_id)
    instrument_id: str = ""
    instrument_code: str = ""
    instrument_name: str = ""
    planned_date: str = ""
    status: str = STATUS_PENDING
    operator: str = ""
    actual_date: Optional[str] = None
    result: str = ""
    is_overdue: bool = False
    overdue_reason: str = ""
    reviewer: str = ""
    review_comment: str = ""
    certificate_summary: str = ""
    cancelled_by: str = ""
    cancel_reason: str = ""
    created_at: str = field(default_factory=_today_str)
    updated_at: str = field(default_factory=_today_str)
    archived_at: Optional[str] = None

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "CalibrationRecord":
        return cls(**d)


def parse_date(s: str) -> Optional[date]:
    if not s:
        return None
    try:
        return datetime.strptime(s, "%Y-%m-%d").date()
    except (ValueError, TypeError):
        return None


def is_valid_date(s: str) -> bool:
    return parse_date(s) is not None


def add_days(date_str: str, days: int) -> str:
    d = parse_date(date_str)
    if d is None:
        return ""
    from datetime import timedelta
    return (d + timedelta(days=days)).isoformat()
