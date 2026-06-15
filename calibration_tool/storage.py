import json
import os
import shutil
from datetime import date
from typing import List, Optional, Dict

from .models import (
    Instrument, CalibrationRecord, User, TransitionLog,
    STATUS_PENDING, STATUS_COMPLETED, STATUS_REVIEWING,
    STATUS_ARCHIVED, STATUS_CANCELLED,
    ACTION_SUBMIT, ACTION_SEND_REVIEW, ACTION_REVIEW_ARCHIVE,
    ACTION_CANCEL, ACTION_UNDO, UNDOABLE_ACTIONS,
    parse_date, is_valid_date,
    is_terminal_status, can_undo_action, can_undo_status
)


class StorageError(Exception):
    pass


class ValidationError(Exception):
    pass


class Storage:
    def __init__(self, data_dir: str):
        self.data_dir = data_dir
        self.instruments_file = os.path.join(data_dir, "instruments.json")
        self.records_file = os.path.join(data_dir, "records.json")
        self.users_file = os.path.join(data_dir, "users.json")
        self.history_file = os.path.join(data_dir, "history.json")
        self.cancelled_records_file = os.path.join(data_dir, "cancelled_records.json")
        os.makedirs(data_dir, exist_ok=True)
        self._ensure_files()

    def _ensure_files(self):
        for f in [self.instruments_file, self.records_file,
                  self.users_file, self.history_file, self.cancelled_records_file]:
            if not os.path.exists(f):
                with open(f, "w", encoding="utf-8") as fp:
                    json.dump([], fp, ensure_ascii=False, indent=2)

    def _read_json(self, path: str) -> list:
        try:
            with open(path, "r", encoding="utf-8") as fp:
                data = json.load(fp)
                if not isinstance(data, list):
                    return []
                return data
        except (json.JSONDecodeError, FileNotFoundError):
            return []

    def _write_json(self, path: str, data: list):
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fp:
            json.dump(data, fp, ensure_ascii=False, indent=2)
        shutil.move(tmp, path)

    # ---- Users ----
    def load_users(self) -> List[User]:
        return [User.from_dict(d) for d in self._read_json(self.users_file)]

    def save_users(self, users: List[User]):
        self._write_json(self.users_file, [u.to_dict() for u in users])

    # ---- Instruments ----
    def load_instruments(self) -> List[Instrument]:
        return [Instrument.from_dict(d) for d in self._read_json(self.instruments_file)]

    def save_instruments(self, instruments: List[Instrument]):
        self._write_json(self.instruments_file, [i.to_dict() for i in instruments])

    def add_instrument(self, inst: Instrument) -> Instrument:
        instruments = self.load_instruments()
        for existing in instruments:
            if existing.code == inst.code:
                raise ValidationError(f"仪器编号 '{inst.code}' 已存在，不允许重复")
        instruments.append(inst)
        self.save_instruments(instruments)
        return inst

    def update_instrument(self, inst: Instrument) -> Instrument:
        instruments = self.load_instruments()
        for i, existing in enumerate(instruments):
            if existing.id == inst.id:
                if existing.code != inst.code:
                    for other in instruments:
                        if other.id != inst.id and other.code == inst.code:
                            raise ValidationError(f"仪器编号 '{inst.code}' 已存在，不允许重复")
                instruments[i] = inst
                self.save_instruments(instruments)
                return inst
        raise StorageError(f"仪器不存在: {inst.id}")

    def get_instrument_by_code(self, code: str) -> Optional[Instrument]:
        for inst in self.load_instruments():
            if inst.code == code:
                return inst
        return None

    def get_instrument_by_id(self, iid: str) -> Optional[Instrument]:
        for inst in self.load_instruments():
            if inst.id == iid:
                return inst
        return None

    # ---- Calibration Records ----
    def load_records(self) -> List[CalibrationRecord]:
        return [CalibrationRecord.from_dict(d) for d in self._read_json(self.records_file)]

    def save_records(self, records: List[CalibrationRecord]):
        self._write_json(self.records_file, [r.to_dict() for r in records])

    def add_record(self, record: CalibrationRecord) -> CalibrationRecord:
        records = self.load_records()
        records.append(record)
        self.save_records(records)
        return record

    def update_record(self, record: CalibrationRecord) -> CalibrationRecord:
        records = self.load_records()
        for i, existing in enumerate(records):
            if existing.id == record.id:
                records[i] = record
                self.save_records(records)
                return record
        raise StorageError(f"校准记录不存在: {record.id}")

    def get_record_by_id(self, rid: str) -> Optional[CalibrationRecord]:
        for r in self.load_records():
            if r.id == rid:
                return r
        return None

    # ---- Cancelled Records ----
    def load_cancelled_records(self) -> List[CalibrationRecord]:
        return [CalibrationRecord.from_dict(d) for d in self._read_json(self.cancelled_records_file)]

    def save_cancelled_records(self, records: List[CalibrationRecord]):
        self._write_json(self.cancelled_records_file, [r.to_dict() for r in records])

    def add_cancelled_record(self, record: CalibrationRecord):
        records = self.load_cancelled_records()
        records.append(record)
        self.save_cancelled_records(records)

    # ---- Transition History ----
    def load_history(self) -> List[TransitionLog]:
        return [TransitionLog.from_dict(d) for d in self._read_json(self.history_file)]

    def save_history(self, history: List[TransitionLog]):
        self._write_json(self.history_file, [h.to_dict() for h in history])

    def add_history(self, log: TransitionLog) -> TransitionLog:
        history = self.load_history()
        history.append(log)
        self.save_history(history)
        return log

    def update_history(self, log: TransitionLog) -> TransitionLog:
        history = self.load_history()
        for i, existing in enumerate(history):
            if existing.id == log.id:
                history[i] = log
                self.save_history(history)
                return log
        raise StorageError(f"历史记录不存在: {log.id}")

    def get_history_for_record(self, record_id: str) -> List[TransitionLog]:
        return sorted(
            [h for h in self.load_history() if h.record_id == record_id],
            key=lambda h: h.created_at
        )

    def get_last_undoable_transition(self, record_id: str) -> Optional[TransitionLog]:
        rec = self.get_record_by_id(record_id)
        if rec is None:
            return None
        if not can_undo_status(rec.status):
            return None
        logs = [h for h in self.load_history()
                if h.record_id == record_id and not h.is_undone
                and can_undo_action(h.action)
                and h.to_status == rec.status]
        logs.sort(key=lambda h: h.created_at, reverse=True)
        return logs[0] if logs else None
