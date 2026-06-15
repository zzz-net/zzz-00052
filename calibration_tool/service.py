import csv
import os
from datetime import date, timedelta
from typing import List, Optional, Tuple

from .models import (
    Instrument, CalibrationRecord, User, TransitionLog,
    STATUS_PENDING, STATUS_COMPLETED, STATUS_REVIEWING,
    STATUS_ARCHIVED, STATUS_CANCELLED,
    ROLE_OPERATOR, ROLE_REVIEWER,
    ACTION_SUBMIT, ACTION_SEND_REVIEW, ACTION_REVIEW_ARCHIVE,
    ACTION_CANCEL, ACTION_UNDO, UNDOABLE_ACTIONS,
    parse_date, is_valid_date, add_days, _today_str, _now_str,
    get_available_actions, get_status_info, get_action_info,
    is_terminal_status, get_terminal_rule,
    can_undo_action, can_undo_status, can_cancel_status,
    get_undo_denied_reason, get_cancel_denied_reason,
    get_status_summary_label,
    setup_logger
)
from typing import Dict, Any
from .storage import Storage, ValidationError, StorageError


class CalibrationService:
    def __init__(self, storage: Storage, enable_file_log: bool = None):
        self.storage = storage
        if enable_file_log is None:
            enable_file_log = not os.environ.get("PYTEST_CURRENT_TEST")
        self.logger = setup_logger(
            storage.data_dir if storage else None,
            enable_file_log=enable_file_log
        )

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

    # ---- State transitions ----
    def _check_permission(self, user: User, action: str):
        if action == "review" and user.role != ROLE_REVIEWER:
            raise ValidationError("当前用户无复核权限，请切换为复核员角色")
        if action == "cancel_review" and user.role != ROLE_REVIEWER:
            raise ValidationError("当前用户无取消权限，请切换为复核员角色")
        if action == "undo" and user.role != ROLE_REVIEWER:
            raise ValidationError("当前用户无撤销权限，请切换为复核员角色")

    def _log_transition(self, record: CalibrationRecord, action: str,
                        from_status: str, to_status: str, user: User,
                        reason: str = "", instrument_snapshot: dict = None,
                        record_snapshot: dict = None) -> TransitionLog:
        log = TransitionLog(
            record_id=record.id,
            action=action,
            from_status=from_status,
            to_status=to_status,
            by_user=user.username,
            reason=reason,
            record_snapshot=record_snapshot if record_snapshot is not None else record.snapshot(),
            instrument_snapshot=instrument_snapshot or {},
        )
        return self.storage.add_history(log)

    def list_history(self, record_id: str = None) -> List[TransitionLog]:
        if record_id:
            return self.storage.get_history_for_record(record_id)
        return sorted(self.storage.load_history(), key=lambda h: h.created_at)

    def list_cancelled_records(self) -> List[CalibrationRecord]:
        return [r for r in self.storage.load_records() if r.status == STATUS_CANCELLED]

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

        from_status = rec.status
        snap_rec = rec.snapshot()
        inst = self.storage.get_instrument_by_id(rec.instrument_id)
        snap_inst = inst.snapshot() if inst else {}

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
        rec.instrument_last_calibration_before = snap_inst.get("last_calibration_date")

        if inst is not None:
            inst.last_calibration_date = actual_date
            self.storage.update_instrument(inst)

        self._log_transition(
            rec, ACTION_SUBMIT,
            from_status=from_status, to_status=rec.status,
            user=user, reason=rec.overdue_reason,
            instrument_snapshot=snap_inst,
            record_snapshot=snap_rec
        )
        self.storage.update_record(rec)
        self.logger.info(
            f"[STATE TRANSITION] 记录 {rec.instrument_code} ({rec.id}): "
            f"{from_status} → {rec.status} | 操作: {ACTION_SUBMIT} | 操作人: {user.username} | 结果: {result}"
        )
        return rec

    def send_for_review(self, record_id: str, user: User) -> CalibrationRecord:
        rec = self.storage.get_record_by_id(record_id)
        if rec is None:
            raise StorageError(f"校准记录不存在: {record_id}")
        if rec.status != STATUS_COMPLETED:
            raise ValidationError(f"只有'{STATUS_COMPLETED}'状态的记录才能提交复核")

        from_status = rec.status
        snap_rec = rec.snapshot()

        rec.status = STATUS_REVIEWING
        rec.updated_at = _today_str()

        self._log_transition(
            rec, ACTION_SEND_REVIEW,
            from_status=from_status, to_status=rec.status,
            user=user,
            record_snapshot=snap_rec
        )
        self.storage.update_record(rec)
        self.logger.info(
            f"[STATE TRANSITION] 记录 {rec.instrument_code} ({rec.id}): "
            f"{from_status} → {rec.status} | 操作: {ACTION_SEND_REVIEW} | 操作人: {user.username}"
        )
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

        from_status = rec.status
        snap_rec = rec.snapshot()

        rec.reviewer = user.username
        rec.review_comment = review_comment.strip()
        if certificate_summary.strip():
            rec.certificate_summary = certificate_summary.strip()
        rec.status = STATUS_ARCHIVED
        rec.archived_at = _today_str()
        rec.updated_at = _today_str()

        self._log_transition(
            rec, ACTION_REVIEW_ARCHIVE,
            from_status=from_status, to_status=rec.status,
            user=user, reason=rec.review_comment,
            record_snapshot=snap_rec
        )
        self.storage.update_record(rec)
        self.logger.info(
            f"[STATE TRANSITION] 记录 {rec.instrument_code} ({rec.id}): "
            f"{from_status} → {rec.status} | 操作: {ACTION_REVIEW_ARCHIVE} | 操作人: {user.username} | 复核意见: {review_comment[:50]}"
        )
        return rec

    def cancel_record(self, record_id: str, user: User,
                      cancel_reason: str = "") -> CalibrationRecord:
        self._check_permission(user, "cancel_review")
        if not cancel_reason.strip():
            raise ValidationError("取消原因不能为空")
        rec = self.storage.get_record_by_id(record_id)
        if rec is None:
            raise StorageError(f"校准记录不存在: {record_id}")
        if not can_cancel_status(rec.status):
            raise ValidationError(get_cancel_denied_reason(rec.status))

        from_status = rec.status
        snap_rec = rec.snapshot()
        inst = self.storage.get_instrument_by_id(rec.instrument_id)
        snap_inst = inst.snapshot() if inst else {}

        rec.cancelled_by = user.username
        rec.cancel_reason = cancel_reason.strip()
        rec.status = STATUS_CANCELLED
        rec.updated_at = _today_str()

        self._log_transition(
            rec, ACTION_CANCEL,
            from_status=from_status, to_status=rec.status,
            user=user, reason=rec.cancel_reason,
            instrument_snapshot=snap_inst,
            record_snapshot=snap_rec
        )
        self.storage.update_record(rec)
        self.logger.warning(
            f"[RECORD CANCELLED] 记录 {rec.instrument_code} ({rec.id}): "
            f"{from_status} → {rec.status} | 操作: {ACTION_CANCEL} | 操作人: {user.username} | 原因: {cancel_reason}"
        )
        return rec

    # ---- Undo last transition ----
    def get_undoable_transition(self, record_id: str) -> Optional[TransitionLog]:
        last = self.storage.get_last_undoable_transition(record_id)
        return last

    def undo_last_transition(self, record_id: str, user: User) -> CalibrationRecord:
        self._check_permission(user, "undo")

        last = self.storage.get_last_undoable_transition(record_id)
        if last is None:
            rec = self.storage.get_record_by_id(record_id)
            if rec is not None:
                denied_reason = get_undo_denied_reason(rec.status, last.action if last else None)
                if denied_reason:
                    raise ValidationError(denied_reason)
            raise ValidationError("该记录无可撤销的流转操作")

        rec = self.storage.get_record_by_id(record_id)
        if rec is None:
            raise StorageError(f"校准记录不存在: {record_id}")

        if not can_undo_status(rec.status):
            raise ValidationError(get_undo_denied_reason(rec.status))

        if rec.status != last.to_status:
            raise ValidationError("记录当前状态与最后一次流转不符，无法撤销")

        if not can_undo_action(last.action):
            raise ValidationError(get_undo_denied_reason(rec.status, last.action))

        snap_before = last.record_snapshot
        if not snap_before:
            raise ValidationError("历史快照缺失，无法撤销")

        from_status = rec.status
        to_status = snap_before.get("status", from_status)

        rec.restore_from(snap_before)
        rec.updated_at = _today_str()

        inst = None
        if last.instrument_snapshot:
            inst = self.storage.get_instrument_by_id(rec.instrument_id)
            if inst is not None and last.action == ACTION_SUBMIT:
                inst.last_calibration_date = last.instrument_snapshot.get("last_calibration_date")
                self.storage.update_instrument(inst)

        self._log_transition(
            rec, ACTION_UNDO,
            from_status=from_status,
            to_status=to_status,
            user=user,
            reason=f"撤销操作：{last.action}",
            instrument_snapshot=last.instrument_snapshot,
            record_snapshot=rec.snapshot()
        )

        last.is_undone = True
        last.undone_by = user.username
        last.undone_at = _now_str()
        self.storage.update_history(last)

        self.storage.update_record(rec)
        self.logger.warning(
            f"[TRANSITION UNDONE] 记录 {rec.instrument_code} ({rec.id}): "
            f"{from_status} → {to_status} | 撤销操作: {last.action} | 操作人: {user.username} | 撤销人: {last.undone_by}"
        )
        return rec

    # ---- Transition Summary (Single source of truth) ----
    def get_transition_summary(self, record_id: str, user: User = None) -> Dict[str, Any]:
        rec = self.storage.get_record_by_id(record_id)
        if rec is None:
            self.logger.error(f"[SUMMARY ERROR] 记录不存在: {record_id}")
            raise StorageError(f"校准记录不存在: {record_id}")

        self.logger.debug(
            f"[SUMMARY GENERATED] 记录 {rec.instrument_code} ({record_id}): "
            f"状态={rec.status} | 查询用户={user.username if user else '未指定'} | 角色={user.role if user else '未指定'}"
            f" | 是否终态={is_terminal_status(rec.status)}"
        )

        user_role = user.role if user else None

        is_terminal = is_terminal_status(rec.status)
        terminal_rule = get_terminal_rule(rec.status)
        terminal_reason = terminal_rule["reason"] if terminal_rule else ""

        status_info = get_status_info(rec.status)
        available_actions = get_available_actions(rec.status, user_role)

        undo_info = None
        if is_terminal:
            undo_info = {
                "is_terminal": True,
                "terminal_reason": terminal_reason,
                "action": "",
                "action_description": "",
                "by_user": "",
                "created_at": "",
                "from_status": "",
                "to_status": rec.status,
                "undo_returns_to_status": "",
                "undo_returns_to_description": terminal_reason,
                "undo_returns_to_status_info": get_status_info(rec.status),
                "reason": "",
                "can_do": False,
                "undo_role_missing": False,
                "required_role": ROLE_REVIEWER,
            }
            self.logger.debug(
                f"[SUMMARY TERMINAL] 记录 {rec.instrument_code} ({record_id}) "
                f"处于终态「{rec.status}」: {terminal_reason}"
            )
        else:
            last_undoable = self.get_undoable_transition(record_id)
            if last_undoable:
                action_rule = get_action_info(last_undoable.action)
                undo_returns_to_status = last_undoable.from_status
                if action_rule["undo_returns_to"] is not None:
                    undo_returns_to_status = action_rule["undo_returns_to"]
                undo_returns_info = get_status_info(undo_returns_to_status)

                can_undo = (user_role == ROLE_REVIEWER) if user_role is not None else False
                undo_role_missing = (user_role is not None and user_role != ROLE_REVIEWER)

                undo_info = {
                    "is_terminal": False,
                    "terminal_reason": "",
                    "action": last_undoable.action,
                    "action_description": action_rule["description"],
                    "by_user": last_undoable.by_user,
                    "created_at": last_undoable.created_at,
                    "from_status": last_undoable.from_status,
                    "to_status": last_undoable.to_status,
                    "undo_returns_to_status": undo_returns_to_status,
                    "undo_returns_to_description": action_rule["undo_returns_to_description"],
                    "undo_returns_to_status_info": undo_returns_info,
                    "reason": last_undoable.reason,
                    "can_do": can_undo,
                    "undo_role_missing": undo_role_missing,
                    "required_role": ROLE_REVIEWER,
                }

        history = self.list_history(record_id)
        history_count = len(history)
        undo_count = len([h for h in history if h.is_undone])

        why_here = ""
        if history:
            last_log = history[-1]
            if last_log.action == ACTION_UNDO:
                why_here = f"通过「撤销流转」操作从「{last_log.from_status}」恢复到此状态"
            else:
                why_here = f"通过「{last_log.action}」操作于 {last_log.created_at} 到达此状态，操作人: {last_log.by_user}"
                if last_log.reason:
                    why_here += f"，原因: {last_log.reason}"
                if is_terminal and last_log.action == ACTION_REVIEW_ARCHIVE:
                    why_here += f"（{terminal_reason}）"
        else:
            why_here = "通过「生成校准计划」功能创建，尚未执行任何流转操作"

        summary = {
            "record_id": rec.id,
            "instrument_code": rec.instrument_code,
            "instrument_name": rec.instrument_name,
            "current_status": rec.status,
            "current_status_info": status_info,
            "is_terminal": is_terminal,
            "terminal_reason": terminal_reason,
            "status_label": get_status_summary_label(rec.status),
            "why_here": why_here,
            "available_actions": available_actions,
            "undo_info": undo_info,
            "history_count": history_count,
            "undo_count": undo_count,
            "user_role": user_role,
        }
        return summary

    # ---- Export ----
    def export_csv(self, filepath: str, records: Optional[List[CalibrationRecord]] = None) -> int:
        if records is None:
            records = self.storage.load_records()

        self.logger.info(
            f"[EXPORT CSV] 开始导出: {filepath} | 记录数: {len(records)}"
        )
        fieldnames = [
            "id", "instrument_code", "instrument_name", "planned_date",
            "status", "operator", "actual_date", "result", "is_overdue",
            "overdue_reason", "reviewer", "review_comment",
            "certificate_summary", "cancelled_by", "cancel_reason",
            "created_at", "updated_at", "archived_at",
            "is_terminal", "terminal_reason",
            "status_description", "why_here", "history_count",
            "undo_count", "last_undoable_action", "undo_returns_to_status"
        ]
        with open(filepath, "w", encoding="utf-8-sig", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            for r in records:
                summary = self.get_transition_summary(r.id)
                row = {k: (getattr(r, k) if getattr(r, k) is not None else "")
                       for k in fieldnames[:18]}
                row["is_terminal"] = "是" if summary.get("is_terminal") else "否"
                row["terminal_reason"] = summary.get("terminal_reason", "")
                row["status_description"] = summary["current_status_info"].get("description", "")
                row["why_here"] = summary["why_here"]
                row["history_count"] = summary["history_count"]
                row["undo_count"] = summary["undo_count"]
                if summary["undo_info"] and not summary["undo_info"].get("is_terminal"):
                    row["last_undoable_action"] = summary["undo_info"]["action"]
                    row["undo_returns_to_status"] = summary["undo_info"]["undo_returns_to_status"]
                else:
                    row["last_undoable_action"] = ""
                    row["undo_returns_to_status"] = ""
                writer.writerow(row)
        self.logger.info(f"[EXPORT CSV] 导出完成: {filepath} | 共 {len(records)} 条记录")
        return len(records)

    def export_html(self, filepath: str, records: Optional[List[CalibrationRecord]] = None) -> int:
        if records is None:
            records = self.storage.load_records()

        self.logger.info(
            f"[EXPORT HTML] 开始导出: {filepath} | 记录数: {len(records)}"
        )
        headers = ["编号", "仪器编号", "仪器名称", "计划日期", "状态", "终态", "终态原因", "状态说明", "为什么在这",
                   "操作员", "实际日期", "结果", "超期", "超期原因",
                   "复核人", "复核意见", "证书摘要", "流转次数", "可撤销次数",
                   "最近可撤销操作", "撤销返回状态", "创建时间", "归档时间"]
        keys = ["id", "instrument_code", "instrument_name", "planned_date",
                "status", "is_terminal", "terminal_reason", "status_description", "why_here",
                "operator", "actual_date", "result", "is_overdue",
                "overdue_reason", "reviewer", "review_comment",
                "certificate_summary", "history_count", "undo_count",
                "last_undoable_action", "undo_returns_to_status",
                "created_at", "archived_at"]
        rows_html = []
        for r in records:
            summary = self.get_transition_summary(r.id)
            cells = []
            for k in keys:
                if k == "status_description":
                    v = summary["current_status_info"].get("description", "")
                elif k == "is_terminal":
                    v = "是(终态)" if summary.get("is_terminal") else "否"
                elif k == "terminal_reason":
                    v = summary.get("terminal_reason", "")
                elif k == "why_here":
                    v = summary["why_here"]
                elif k == "history_count":
                    v = str(summary["history_count"])
                elif k == "undo_count":
                    v = str(summary["undo_count"])
                elif k == "last_undoable_action":
                    v = summary["undo_info"]["action"] if (summary["undo_info"] and not summary["undo_info"].get("is_terminal")) else ""
                elif k == "undo_returns_to_status":
                    v = summary["undo_info"]["undo_returns_to_status"] if (summary["undo_info"] and not summary["undo_info"].get("is_terminal")) else ""
                else:
                    v = getattr(r, k)
                    if v is None:
                        v = ""
                    if isinstance(v, bool):
                        v = "是" if v else "否"
                cells.append(f"<td>{v}</td>")
            status_class = f"status-{r.status}"
            rows_html.append(f'<tr class="{status_class}">' + "".join(cells) + "</tr>")
        html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head><meta charset="UTF-8"><title>校准记录导出</title>
<style>
body {{ font-family: "Microsoft YaHei", sans-serif; margin: 20px; }}
h1 {{ color: #2c3e50; }}
.audit-info {{ background-color: #f8f9fa; border-left: 4px solid #3498db; padding: 12px 16px; margin: 16px 0; border-radius: 4px; }}
.audit-info h3 {{ margin: 0 0 8px 0; color: #2c3e50; font-size: 14px; }}
.audit-info p {{ margin: 4px 0; font-size: 13px; color: #34495e; }}
table {{ border-collapse: collapse; width: 100%; margin-top: 20px; table-layout: fixed; }}
th, td {{ border: 1px solid #ddd; padding: 6px 10px; text-align: left; vertical-align: top; word-wrap: break-word; font-size: 12px; }}
th {{ background-color: #3498db; color: white; white-space: nowrap; }}
tr:nth-child(even) {{ background-color: #f9f9f9; }}
.status-待执行 td:nth-child(5) {{ color: #e67e22; font-weight: bold; }}
.status-已完成 td:nth-child(5) {{ color: #27ae60; font-weight: bold; }}
.status-待复核 td:nth-child(5) {{ color: #2980b9; font-weight: bold; }}
.status-归档 td:nth-child(5) {{ color: #7f8c8d; font-weight: bold; }}
.status-取消 td:nth-child(5) {{ color: #c0392b; font-weight: bold; }}
.summary-section {{ background-color: #eef7ff; border: 1px solid #b3d9ff; border-radius: 6px; padding: 16px; margin: 20px 0; }}
.summary-section h2 {{ margin-top: 0; color: #2c3e50; font-size: 16px; border-bottom: 2px solid #3498db; padding-bottom: 8px; }}
.stat-cards {{ display: flex; gap: 12px; flex-wrap: wrap; margin: 12px 0; }}
.stat-card {{ background: white; border-radius: 6px; padding: 12px 16px; box-shadow: 0 1px 3px rgba(0,0,0,0.1); flex: 1; min-width: 140px; }}
.stat-card .label {{ font-size: 12px; color: #7f8c8d; margin-bottom: 4px; }}
.stat-card .value {{ font-size: 22px; font-weight: bold; color: #2c3e50; }}
.legend {{ display: flex; flex-wrap: wrap; gap: 16px; margin-top: 8px; }}
.legend-item {{ display: flex; align-items: center; gap: 6px; font-size: 12px; }}
.legend-dot {{ width: 12px; height: 12px; border-radius: 50%; }}
</style></head>
<body>
<h1>仪器校准记录导出</h1>
<p>导出时间: {_today_str()} | 共 {len(records)} 条记录</p>

<div class="audit-info">
  <h3>📋 审计链路说明</h3>
  <p><strong>数据来源：</strong>本导出文件与系统界面使用同一套流转规则定义（STATUS_RULES / ACTION_RULES / TERMINAL_RULES），界面提示、规则校验、历史记录、导出内容共用唯一真相来源。</p>
  <p><strong>终态规则（唯一来源 TERMINAL_RULES）：</strong>归档为终态，校准流程全部完成，不可再撤销或变更。终态判断统一通过 <code>is_terminal_status()</code> 函数，所有模块共用。</p>
  <p><strong>字段说明：</strong>「状态说明」解释当前状态含义；「为什么在这」说明到达此状态的最近一次操作和原因；「最近可撤销操作」+「撤销返回状态」用于审计可追溯的回退路径；「终态」+「终态原因」明确标识不可变更的记录。</p>
  <p><strong>一致性保证：</strong>重启后重新打开系统，摘要、历史条数、可执行动作、终态标识均从存储层加载，与导出时保持一致。</p>
</div>

<div class="summary-section">
  <h2>📊 流转统计总览</h2>
  <div class="stat-cards">
    <div class="stat-card">
      <div class="label">总记录数</div>
      <div class="value">{len(records)}</div>
    </div>
"""
        pending_count = len([r for r in records if r.status == STATUS_PENDING])
        completed_count = len([r for r in records if r.status == STATUS_COMPLETED])
        reviewing_count = len([r for r in records if r.status == STATUS_REVIEWING])
        archived_count = len([r for r in records if r.status == STATUS_ARCHIVED])
        cancelled_count = len([r for r in records if r.status == STATUS_CANCELLED])
        terminal_count = len([r for r in records if is_terminal_status(r.status)])
        total_history = sum(len(self.list_history(r.id)) for r in records)
        total_undoable = sum(1 for r in records if self.get_undoable_transition(r.id))

        html += f"""
    <div class="stat-card">
      <div class="label">待执行</div>
      <div class="value" style="color:#e67e22;">{pending_count}</div>
    </div>
    <div class="stat-card">
      <div class="label">已完成</div>
      <div class="value" style="color:#27ae60;">{completed_count}</div>
    </div>
    <div class="stat-card">
      <div class="label">待复核</div>
      <div class="value" style="color:#2980b9;">{reviewing_count}</div>
    </div>
    <div class="stat-card">
      <div class="label">已归档(终态)</div>
      <div class="value" style="color:#7f8c8d;">{archived_count}</div>
    </div>
    <div class="stat-card">
      <div class="label">已取消</div>
      <div class="value" style="color:#c0392b;">{cancelled_count}</div>
    </div>
    <div class="stat-card">
      <div class="label">🔒 终态总数</div>
      <div class="value" style="color:#2c3e50;">{terminal_count}</div>
    </div>
    <div class="stat-card">
      <div class="label">流转日志总条数</div>
      <div class="value" style="color:#8e44ad;">{total_history}</div>
    </div>
    <div class="stat-card">
      <div class="label">当前可撤销记录数</div>
      <div class="value" style="color:#16a085;">{total_undoable}</div>
    </div>
  </div>
  <div class="legend">
    <div class="legend-item"><span class="legend-dot" style="background:#e67e22;"></span>待执行 - 等待操作员校准</div>
    <div class="legend-item"><span class="legend-dot" style="background:#27ae60;"></span>已完成 - 等待提交复核</div>
    <div class="legend-item"><span class="legend-dot" style="background:#2980b9;"></span>待复核 - 等待复核员归档</div>
    <div class="legend-item"><span class="legend-dot" style="background:#7f8c8d;"></span>归档 - 终态，不可撤销</div>
    <div class="legend-item"><span class="legend-dot" style="background:#c0392b;"></span>取消 - 已取消可恢复</div>
    <div class="legend-item"><span class="legend-dot" style="background:#2c3e50;"></span>🔒 终态 - 不可变更</div>
  </div>
</div>

<table>
<thead><tr>{"".join(f"<th>{h}</th>" for h in headers)}</tr></thead>
<tbody>{''.join(rows_html)}</tbody>
</table>
</body></html>"""
        with open(filepath, "w", encoding="utf-8") as f:
            f.write(html)
        self.logger.info(f"[EXPORT HTML] 导出完成: {filepath} | 共 {len(records)} 条记录")
        return len(records)
