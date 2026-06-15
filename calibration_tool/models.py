from dataclasses import dataclass, field, asdict
from datetime import date, datetime
from typing import Optional, List
import uuid
import logging
import os

def setup_logger(data_dir: str = None, enable_file_log: bool = True) -> logging.Logger:
    logger = logging.getLogger("calibration_tool")

    for handler in logger.handlers[:]:
        logger.removeHandler(handler)
        handler.close()

    logger.setLevel(logging.DEBUG)

    formatter = logging.Formatter(
        "%(asctime)s | %(levelname)-7s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S"
    )

    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.WARNING)
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)

    if data_dir and enable_file_log:
        os.makedirs(data_dir, exist_ok=True)
        log_file = os.path.join(data_dir, "calibration_tool.log")
        try:
            file_handler = logging.FileHandler(log_file, encoding="utf-8", delay=True)
            file_handler.setLevel(logging.DEBUG)
            file_handler.setFormatter(formatter)
            logger.addHandler(file_handler)
        except (PermissionError, OSError):
            pass

    logger.propagate = False
    return logger


def close_logger():
    logger = logging.getLogger("calibration_tool")
    for handler in logger.handlers[:]:
        logger.removeHandler(handler)
        try:
            handler.close()
        except Exception:
            pass


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


def _now_str() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


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

    def snapshot(self) -> dict:
        return asdict(self)

    def restore_from(self, snapshot: dict):
        for k, v in snapshot.items():
            if hasattr(self, k):
                setattr(self, k, v)


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
    instrument_last_calibration_before: Optional[str] = None

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "CalibrationRecord":
        return cls(**d)

    def snapshot(self) -> dict:
        return asdict(self)

    def restore_from(self, snapshot: dict):
        for k, v in snapshot.items():
            if hasattr(self, k):
                setattr(self, k, v)


@dataclass
class TransitionLog:
    id: str = field(default_factory=_new_id)
    record_id: str = ""
    action: str = ""
    from_status: str = ""
    to_status: str = ""
    by_user: str = ""
    reason: str = ""
    record_snapshot: dict = field(default_factory=dict)
    instrument_snapshot: dict = field(default_factory=dict)
    created_at: str = field(default_factory=_now_str)
    is_undone: bool = False
    undone_by: str = ""
    undone_at: Optional[str] = None

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "TransitionLog":
        return cls(**d)


ACTION_SUBMIT = "录入校准"
ACTION_SEND_REVIEW = "提交复核"
ACTION_REVIEW_ARCHIVE = "复核归档"
ACTION_CANCEL = "取消记录"
ACTION_UNDO = "撤销流转"

TERMINAL_STATUSES = {STATUS_ARCHIVED}

TERMINAL_RULES = {
    STATUS_ARCHIVED: {
        "reason": "归档为终态，校准流程全部完成，不可再撤销或变更。",
        "cannot_cancel": True,
        "cannot_undo": True,
    },
}

UNDOABLE_ACTIONS = [ACTION_SUBMIT, ACTION_SEND_REVIEW, ACTION_CANCEL]

STATUS_RULES = {
    STATUS_PENDING: {
        "label": STATUS_PENDING,
        "description": "校准计划已生成，等待操作员执行实际校准工作。",
        "how_got_here": [
            "通过「生成校准计划」功能，根据仪器台账自动创建",
            "撤销「录入校准」操作后回到此状态",
            "撤销「取消记录」操作后回到此状态",
        ],
        "color": "#e67e22",
        "is_terminal": False,
    },
    STATUS_COMPLETED: {
        "label": STATUS_COMPLETED,
        "description": "操作员已录入校准结果，等待提交给复核员进行复核。",
        "how_got_here": [
            "操作员执行「录入校准」操作，填写实际校准日期和结果",
            "撤销「提交复核」操作后回到此状态",
            "撤销「取消记录」操作后回到此状态",
        ],
        "color": "#27ae60",
        "is_terminal": False,
    },
    STATUS_REVIEWING: {
        "label": STATUS_REVIEWING,
        "description": "校准结果已提交，等待复核员进行复核并归档。",
        "how_got_here": [
            "操作员或复核员执行「提交复核」操作",
            "撤销「取消记录」操作后回到此状态",
        ],
        "color": "#2980b9",
        "is_terminal": False,
    },
    STATUS_ARCHIVED: {
        "label": STATUS_ARCHIVED,
        "description": "复核员已确认并归档，校准流程全部完成（终态，不可撤销）。",
        "how_got_here": [
            "复核员执行「复核归档」操作，确认校准结果合规（归档后为终态）",
        ],
        "color": "#7f8c8d",
        "is_terminal": True,
    },
    STATUS_CANCELLED: {
        "label": STATUS_CANCELLED,
        "description": "该校准计划被取消，不再执行。可通过撤销恢复。",
        "how_got_here": [
            "复核员对 待执行/已完成/待复核 状态的记录执行「取消记录」操作",
        ],
        "color": "#c0392b",
        "is_terminal": False,
    },
}

ACTION_RULES = {
    ACTION_SUBMIT: {
        "label": ACTION_SUBMIT,
        "description": "录入实际校准结果（日期、结果、证书摘要、超期原因）",
        "required_role": None,
        "from_statuses": [STATUS_PENDING],
        "to_status": STATUS_COMPLETED,
        "to_status_description": "校准完成，等待提交复核",
        "undo_returns_to": STATUS_PENDING,
        "undo_returns_to_description": "回到待执行状态，校准结果被清空",
        "button_label": "录入校准结果",
        "fields_required": ["实际校准日期", "校准结果"],
        "fields_optional": ["证书摘要", "超期原因（超期时必填）"],
    },
    ACTION_SEND_REVIEW: {
        "label": ACTION_SEND_REVIEW,
        "description": "将已完成的校准记录提交给复核员进行复核",
        "required_role": None,
        "from_statuses": [STATUS_COMPLETED],
        "to_status": STATUS_REVIEWING,
        "to_status_description": "已提交复核，等待复核员处理",
        "undo_returns_to": STATUS_COMPLETED,
        "undo_returns_to_description": "回到已完成状态，可重新修改或提交",
        "button_label": "提交复核",
        "fields_required": [],
        "fields_optional": [],
    },
    ACTION_REVIEW_ARCHIVE: {
        "label": ACTION_REVIEW_ARCHIVE,
        "description": "复核员审核校准结果，填写复核意见后完成归档（归档后为终态，不可撤销）",
        "required_role": ROLE_REVIEWER,
        "from_statuses": [STATUS_REVIEWING],
        "to_status": STATUS_ARCHIVED,
        "to_status_description": "复核通过并归档，流程结束（终态，不可撤销）",
        "undo_returns_to": None,
        "undo_returns_to_description": "归档为终态，不可撤销",
        "button_label": "复核并归档",
        "fields_required": ["复核意见"],
        "fields_optional": ["证书摘要（补充）"],
        "is_terminal_action": True,
    },
    ACTION_CANCEL: {
        "label": ACTION_CANCEL,
        "description": "复核员取消该校准计划，记录取消原因",
        "required_role": ROLE_REVIEWER,
        "from_statuses": [STATUS_PENDING, STATUS_COMPLETED, STATUS_REVIEWING],
        "to_status": STATUS_CANCELLED,
        "to_status_description": "记录已取消，可通过撤销恢复",
        "undo_returns_to": None,
        "undo_returns_to_description": "恢复到取消前的状态（待执行/已完成/待复核）",
        "button_label": "取消记录",
        "fields_required": ["取消原因"],
        "fields_optional": [],
    },
    ACTION_UNDO: {
        "label": ACTION_UNDO,
        "description": "复核员撤销最近一次可撤销的流转操作，恢复到操作前状态",
        "required_role": ROLE_REVIEWER,
        "from_statuses": [STATUS_COMPLETED, STATUS_REVIEWING, STATUS_ARCHIVED, STATUS_CANCELLED],
        "to_status": None,
        "to_status_description": "恢复到上一次流转前的状态（取决于被撤销的操作）",
        "undo_returns_to": None,
        "undo_returns_to_description": "撤销操作本身不可再撤销（会生成新的流转记录）",
        "button_label": "撤销上一次流转",
        "fields_required": [],
        "fields_optional": [],
    },
}


def get_available_actions(status: str, user_role: str = None) -> list:
    actions = []
    for action_key, rule in ACTION_RULES.items():
        if action_key == ACTION_UNDO:
            continue
        if status in rule["from_statuses"]:
            if rule["required_role"] is None or rule["required_role"] == user_role:
                can_do = True
                role_missing = False
            else:
                can_do = False
                role_missing = True
            actions.append({
                "action": action_key,
                "label": rule["label"],
                "button_label": rule["button_label"],
                "description": rule["description"],
                "required_role": rule["required_role"],
                "to_status": rule["to_status"],
                "to_status_description": rule["to_status_description"],
                "fields_required": rule["fields_required"],
                "fields_optional": rule["fields_optional"],
                "can_do": can_do,
                "role_missing": role_missing,
            })
    return actions


def get_status_info(status: str) -> dict:
    return STATUS_RULES.get(status, {
        "label": status,
        "description": f"未知状态: {status}",
        "how_got_here": [],
        "color": "#000000",
    })


def get_action_info(action: str) -> dict:
    return ACTION_RULES.get(action, {
        "label": action,
        "description": f"未知操作: {action}",
        "required_role": None,
        "from_statuses": [],
        "to_status": None,
        "to_status_description": "",
        "undo_returns_to": None,
        "undo_returns_to_description": "",
        "button_label": action,
        "fields_required": [],
        "fields_optional": [],
    })


def is_terminal_status(status: str) -> bool:
    return status in TERMINAL_STATUSES


def get_terminal_rule(status: str) -> Optional[dict]:
    return TERMINAL_RULES.get(status)


def can_undo_action(action: str) -> bool:
    return action in UNDOABLE_ACTIONS


def can_undo_status(status: str) -> bool:
    if is_terminal_status(status):
        return False
    return True


def can_cancel_status(status: str) -> bool:
    rule = get_terminal_rule(status)
    if rule and rule.get("cannot_cancel"):
        return False
    if status == STATUS_CANCELLED:
        return False
    return True


def get_undo_denied_reason(status: str, action: str = None) -> str:
    if is_terminal_status(status):
        rule = get_terminal_rule(status)
        if rule:
            return rule["reason"]
        return f"「{status}」为终态，不可撤销"
    if action and not can_undo_action(action):
        info = get_action_info(action)
        desc = info.get("undo_returns_to_description", "该操作不可撤销")
        return desc
    return ""


def get_cancel_denied_reason(status: str) -> str:
    if is_terminal_status(status):
        rule = get_terminal_rule(status)
        if rule and rule.get("cannot_cancel"):
            return f"「{status}」状态的记录无法取消"
    if status == STATUS_CANCELLED:
        return "记录已处于取消状态"
    return ""


def get_status_summary_label(status: str) -> str:
    info = get_status_info(status)
    label = info.get("label", status)
    if is_terminal_status(status):
        return f"【{label}】(终态)"
    return f"【{label}】"


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
