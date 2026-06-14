import csv
import os
from datetime import date, timedelta
from typing import List, Optional, Tuple

from .models import (
    Instrument, CalibrationRecord, User,
    STATUS_PENDING, STATUS_COMPLETED, STATUS_REVIEWING,
    STATUS_ARCHIVED, STATUS_CANCELLED,
    ROLE_OPERATOR, ROLE_REVIEWER,
    parse_date, is_valid_date, add_days, _today_str
)
from .storage import Storage, ValidationError, StorageError


class CalibrationService:
    def __init__(self, storage: Storage):
        self.storage = storage

    # ---- User helpers ----
    def get_current_user(self) -> User:
        users = self.storage.load_users()
        if not users:
            users = [
                User(username="operator1", role=ROLE_OPERATOR),
                User(username="reviewer1", role=ROLE_REVIEWER),
            ]
            self.storage.save_users(users)
        return users[0]

    def get_all_users(self) -> List[User]:
        return self.storage.load_users()

    def set_current_user(self, username: str) -> User:
        users = self.storage.load_users()
        for u in users:
            if u.username == username:
                return u
        raise ValidationError(f"用户不存在: {username}")

    # ---- Instrument management ----
    def list_instruments(self) -> List[Instrument]:
        return [i for i in self.storage.load_instruments() if i.is_active]

    def create_instrument(self, code: str, name: str, model: str = "",
                          manufacturer: str = "", location: str = "",
                          cycle_days: int = 365, last_calibration_date: str = "",
                          owner: str = "", remark: str = "") -> Instrument:
        if not code.strip():
            raise ValidationError("仪器编号不能为空")
        if not name.strip():
            raise ValidationError("仪器名称不能为空")
        if cycle_days <= 0:
            raise ValidationError("校准周期必须是正整数")
        if last_calibration_date and not is_valid_date(last_calibration_date):
            raise ValidationError(f"上次校准日期格式无效: {last_calibration_date}")
        inst = Instrument(
            code=code.strip(),
            name=name.strip(),
            model=model.strip(),
            manufacturer=manufacturer.strip(),
            location=location.strip(),
            cycle_days=cycle_days,
            last_calibration_date=last_calibration_date or None,
            owner=owner.strip(),
            remark=remark.strip(),
        )
        return self.storage.add_instrument(inst)

    def update_instrument(self, inst_id: str, **kwargs) -> Instrument:
        inst = self.storage.get_instrument_by_id(inst_id)
        if inst is None:
            raise StorageError(f"仪器不存在: {inst_id}")
        if "code" in kwargs:
            if not kwargs["code"].strip():
                raise ValidationError("仪器编号不能为空")
        if "name" in kwargs:
            if not kwargs["name"].strip():
                raise ValidationError("仪器名称不能为空")
        if "cycle_days" in kwargs:
            if kwargs["cycle_days"] <= 0:
                raise ValidationError("校准周期必须是正整数")
        if "last_calibration_date" in kwargs:
            d = kwargs["last_calibration_date"]
            if d and not is_valid_date(d):
                raise ValidationError(f"上次校准日期格式无效: {d}")
        for k, v in kwargs.items():
            if hasattr(inst, k):
                if isinstance(v, str) and k not in ("last_calibration_date",):
                    setattr(inst, k, v.strip())
                else:
                    setattr(inst, k, v)
        return self.storage.update_instrument(inst)

    # ---- Plan generation ----
    def generate_plans(self, target_date: str = "") -> List[CalibrationRecord]:
        if not target_date:
            target_date = _today_str()
        if not is_valid_date(target_date):
            raise ValidationError(f"日期格式无效: {target_date}")
        target = parse_date(target_date)
        instruments = self.list_instruments()
        existing = self.storage.load_records()
        existing_pending_ids = set()
        for r in existing:
            if r.status in (STATUS_PENDING, STATUS_COMPLETED, STATUS_REVIEWING):
                existing_pending_ids.add(r.instrument_id)

        new_records: List[CalibrationRecord] = []
        for inst in instruments:
            if inst.id in existing_pending_ids:
                continue
            if inst.last_calibration_date:
                planned = parse_date(inst.last_calibration_date) + timedelta(days=inst.cycle_days)
            else:
                planned = target
            rec = CalibrationRecord(
                instrument_id=inst.id,
                instrument_code=inst.code,
                instrument_name=inst.name,
                planned_date=planned.isoformat(),
                status=STATUS_PENDING,
                operator=inst.owner,
            )
            rec.is_overdue = planned < target
            self.storage.add_record(rec)
            new_records.append(rec)
        return new_records

    # ---- Records query ----
    def list_records(self, status: Optional[str] = None) -> List[CalibrationRecord]:
        records = self.storage.load_records()
        if status:
            records = [r for r in records if r.status == status]
        records.sort(key=lambda r: (r.status, r.planned_date), reverse=False)
        return records

    def list_cancelled_records(self) -> List[CalibrationRecord]:
        return self.storage.load_cancelled_records()

    # ---- State transitions ----
    def _check_permission(self, user: User, action: str):
        if action == "review" and user.role != ROLE_REVIEWER:
            raise ValidationError("当前用户无复核权限，请切换为复核员角色")
        if action == "cancel_review" and user.role != ROLE_REVIEWER:
            raise ValidationError("当前用户无撤销权限，请切换为复核员角色")

    def submit_calibration(self, record_id: str, user: User,
                           actual_date: str, result: str,
                           certificate_summary: str = "",
                           overdue_reason: str = "") -> CalibrationRecord:
        if not actual_date:
            raise ValidationError("实际校准日期不能为空")
        if not is_valid_date(actual_date):
            raise ValidationError(f"实际校准日期格式无效: {actual_date}")
        if not result.strip():
            raise ValidationError("校准结果不能为空")
        rec = self.storage.get_record_by_id(record_id)
        if rec is None:
            raise StorageError(f"校准记录不存在: {record_id}")
        if rec.status != STATUS_PENDING:
            raise ValidationError(f"只有'{STATUS_PENDING}'状态的记录才能录入校准结果")
        actual = parse_date(actual_date)
        planned = parse_date(rec.planned_date)
        rec.actual_date = actual_date
        rec.result = result.strip()
        rec.certificate_summary = certificate_summary.strip()
        rec.operator = user.username
        rec.is_overdue = actual > planned if planned else False
        if rec.is_overdue and not overdue_reason.strip():
            raise ValidationError("校准已超期，必须填写超期原因")
        rec.overdue_reason = overdue_reason.strip()
        rec.status = STATUS_COMPLETED
        rec.updated_at = _today_str()
        self.storage.update_record(rec)

        inst = self.storage.get_instrument_by_id(rec.instrument_id)
        if inst is not None:
            inst.last_calibration_date = actual_date
            self.storage.update_instrument(inst)
        return rec

    def send_for_review(self, record_id: str, user: User) -> CalibrationRecord:
        rec = self.storage.get_record_by_id(record_id)
        if rec is None:
            raise StorageError(f"校准记录不存在: {record_id}")
        if rec.status != STATUS_COMPLETED:
            raise ValidationError(f"只有'{STATUS_COMPLETED}'状态的记录才能提交复核")
        rec.status = STATUS_REVIEWING
        rec.updated_at = _today_str()
        self.storage.update_record(rec)
        return rec

    def review_archive(self, record_id: str, user: User,
                       review_comment: str = "",
                       certificate_summary: str = "") -> CalibrationRecord:
        self._check_permission(user, "review")
        if not review_comment.strip():
            raise ValidationError("复核意见不能为空")
        rec = self.storage.get_record_by_id(record_id)
        if rec is None:
            raise StorageError(f"校准记录不存在: {record_id}")
        if rec.status != STATUS_REVIEWING:
            raise ValidationError(f"只有'{STATUS_REVIEWING}'状态的记录才能复核归档")
        rec.reviewer = user.username
        rec.review_comment = review_comment.strip()
        if certificate_summary.strip():
            rec.certificate_summary = certificate_summary.strip()
        rec.status = STATUS_ARCHIVED
        rec.archived_at = _today_str()
        rec.updated_at = _today_str()
        self.storage.update_record(rec)
        return rec

    def cancel_record(self, record_id: str, user: User,
                      cancel_reason: str = "") -> CalibrationRecord:
        self._check_permission(user, "cancel_review")
        if not cancel_reason.strip():
            raise ValidationError("撤销原因不能为空")
        rec = self.storage.get_record_by_id(record_id)
        if rec is None:
            raise StorageError(f"校准记录不存在: {record_id}")
        if rec.status == STATUS_ARCHIVED:
            raise ValidationError(f"'{STATUS_ARCHIVED}'状态的记录无法撤销")
        if rec.status == STATUS_CANCELLED:
            raise ValidationError(f"记录已处于取消状态")
        rec.cancelled_by = user.username
        rec.cancel_reason = cancel_reason.strip()
        rec.status = STATUS_CANCELLED
        rec.updated_at = _today_str()
        records = [r for r in self.storage.load_records() if r.id != rec.id]
        self.storage.save_records(records)
        self.storage.add_cancelled_record(rec)
        return rec

    # ---- Export ----
    def export_csv(self, filepath: str, records: Optional[List[CalibrationRecord]] = None) -> int:
        if records is None:
            records = self.list_records()
        fieldnames = [
            "id", "instrument_code", "instrument_name", "planned_date",
            "status", "operator", "actual_date", "result", "is_overdue",
            "overdue_reason", "reviewer", "review_comment",
            "certificate_summary", "cancelled_by", "cancel_reason",
            "created_at", "updated_at", "archived_at"
        ]
        with open(filepath, "w", encoding="utf-8-sig", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            for r in records:
                writer.writerow({k: (getattr(r, k) if getattr(r, k) is not None else "")
                                 for k in fieldnames})
        return len(records)

    def export_html(self, filepath: str, records: Optional[List[CalibrationRecord]] = None) -> int:
        if records is None:
            records = self.list_records()
        headers = ["编号", "仪器编号", "仪器名称", "计划日期", "状态",
                   "操作员", "实际日期", "结果", "超期", "超期原因",
                   "复核人", "复核意见", "证书摘要", "创建时间", "归档时间"]
        keys = ["id", "instrument_code", "instrument_name", "planned_date",
                "status", "operator", "actual_date", "result", "is_overdue",
                "overdue_reason", "reviewer", "review_comment",
                "certificate_summary", "created_at", "archived_at"]
        rows_html = []
        for r in records:
            cells = []
            for k in keys:
                v = getattr(r, k)
                if v is None:
                    v = ""
                if isinstance(v, bool):
                    v = "是" if v else "否"
                cells.append(f"<td>{v}</td>")
            rows_html.append("<tr>" + "".join(cells) + "</tr>")
        html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head><meta charset="UTF-8"><title>校准记录导出</title>
<style>
body {{ font-family: "Microsoft YaHei", sans-serif; margin: 20px; }}
h1 {{ color: #2c3e50; }}
table {{ border-collapse: collapse; width: 100%; margin-top: 20px; }}
th, td {{ border: 1px solid #ddd; padding: 8px 12px; text-align: left; }}
th {{ background-color: #3498db; color: white; }}
tr:nth-child(even) {{ background-color: #f9f9f9; }}
.status-待执行 {{ color: #e67e22; font-weight: bold; }}
.status-已完成 {{ color: #27ae60; font-weight: bold; }}
.status-待复核 {{ color: #2980b9; font-weight: bold; }}
.status-归档 {{ color: #7f8c8d; font-weight: bold; }}
.status-取消 {{ color: #c0392b; font-weight: bold; }}
</style></head>
<body>
<h1>仪器校准记录</h1>
<p>导出时间: {_today_str()} | 共 {len(records)} 条记录</p>
<table>
<thead><tr>{"".join(f"<th>{h}</th>" for h in headers)}</tr></thead>
<tbody>{''.join(rows_html)}</tbody>
</table>
</body></html>"""
        with open(filepath, "w", encoding="utf-8") as f:
            f.write(html)
        return len(records)
