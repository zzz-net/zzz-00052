import os
import sys
import shutil
from datetime import date, timedelta
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from calibration_tool import (
    Storage, CalibrationService, CalibrationRecord, User, TransitionLog,
    STATUS_PENDING, STATUS_COMPLETED, STATUS_REVIEWING,
    STATUS_ARCHIVED, STATUS_CANCELLED,
    ROLE_OPERATOR, ROLE_REVIEWER,
    ACTION_SUBMIT, ACTION_SEND_REVIEW, ACTION_REVIEW_ARCHIVE,
    ACTION_CANCEL, ACTION_UNDO,
    ValidationError, StorageError, _today_str, parse_date
)


def fresh_data_dir() -> str:
    base = os.path.dirname(os.path.abspath(__file__))
    path = os.path.join(base, "test_data_tmp")
    if os.path.exists(path):
        shutil.rmtree(path)
    os.makedirs(path)
    return path


def make_users(storage: Storage):
    users = [
        User(username="op1", role=ROLE_OPERATOR),
        User(username="op2", role=ROLE_OPERATOR),
        User(username="rv1", role=ROLE_REVIEWER),
    ]
    storage.save_users(users)
    return users[0], users[2]


def make_test_instrument(svc: CalibrationService, code: str = "T-001",
                          overdue: bool = False):
    today = date.today()
    days_ago = 400 if overdue else 30
    return svc.create_instrument(
        code=code, name=f"测试仪器{code}",
        cycle_days=365,
        last_calibration_date=(today - timedelta(days=days_ago)).isoformat()
    )


class TestTransitionHistory(unittest.TestCase):
    def setUp(self):
        self.data_dir = fresh_data_dir()
        self.storage = Storage(self.data_dir)
        self.svc = CalibrationService(self.storage)
        self.op, self.rv = make_users(self.storage)

    def tearDown(self):
        if os.path.exists(self.data_dir):
            shutil.rmtree(self.data_dir)

    def _make_plan(self, code: str = "T-001"):
        make_test_instrument(self.svc, code)
        plans = self.svc.generate_plans()
        self.assertEqual(len(plans), 1)
        return plans[0]

    def test_cancel_then_undo_pending(self):
        rec = self._make_plan("T-001")
        self.assertEqual(rec.status, STATUS_PENDING)

        # 1. 取消待执行记录（用复核员权限）
        self.svc.cancel_record(rec.id, self.rv, cancel_reason="误操作测试")
        rec = self.storage.get_record_by_id(rec.id)
        self.assertEqual(rec.status, STATUS_CANCELLED)
        self.assertEqual(rec.cancel_reason, "误操作测试")

        all_recs = self.storage.load_records()
        self.assertEqual(len(all_recs), 1, "取消后的记录应保留在主 records.json 中")
        self.assertEqual(all_recs[0].status, STATUS_CANCELLED)

        history = self.svc.list_history(rec.id)
        self.assertEqual(len(history), 1)
        self.assertEqual(history[0].action, ACTION_CANCEL)
        self.assertEqual(history[0].from_status, STATUS_PENDING)
        self.assertEqual(history[0].to_status, STATUS_CANCELLED)
        self.assertEqual(history[0].by_user, self.rv.username)

        # 2. 撤销取消，恢复为待执行
        rec2 = self.svc.undo_last_transition(rec.id, self.rv)
        self.assertEqual(rec2.status, STATUS_PENDING)
        self.assertEqual(rec2.cancel_reason, "")
        self.assertEqual(rec2.cancelled_by, "")

        history = self.svc.list_history(rec.id)
        self.assertEqual(len(history), 2)
        self.assertEqual(history[1].action, ACTION_UNDO)
        self.assertTrue(history[0].is_undone)

    def test_submit_calibration_then_undo(self):
        rec = self._make_plan("T-002")
        today = _today_str()

        rec = self.svc.submit_calibration(
            rec.id, self.op,
            actual_date=today,
            result="合格",
            certificate_summary="CERT-001"
        )
        self.assertEqual(rec.status, STATUS_COMPLETED)
        self.assertEqual(rec.actual_date, today)

        history = self.svc.list_history(rec.id)
        self.assertEqual(history[0].action, ACTION_SUBMIT)
        self.assertEqual(history[0].record_snapshot["status"], STATUS_PENDING)

        last = self.svc.get_undoable_transition(rec.id)
        self.assertIsNotNone(last)
        self.assertEqual(last.action, ACTION_SUBMIT)

        undo_rec = self.svc.undo_last_transition(rec.id, self.rv)
        self.assertEqual(undo_rec.status, STATUS_PENDING)
        self.assertIsNone(undo_rec.actual_date)
        self.assertEqual(undo_rec.result, "")

    def test_send_for_review_then_undo(self):
        rec = self._make_plan("T-003")
        self.svc.submit_calibration(
            rec.id, self.op, actual_date=_today_str(), result="合格")

        rec = self.svc.send_for_review(rec.id, self.op)
        self.assertEqual(rec.status, STATUS_REVIEWING)

        undo_rec = self.svc.undo_last_transition(rec.id, self.rv)
        self.assertEqual(undo_rec.status, STATUS_COMPLETED)

        history = self.svc.list_history(rec.id)
        actions = [h.action for h in history]
        self.assertIn(ACTION_UNDO, actions)

    def test_cancel_after_completed_then_undo(self):
        rec = self._make_plan("T-004")
        self.svc.submit_calibration(
            rec.id, self.op, actual_date=_today_str(), result="合格")
        rec = self.svc.cancel_record(rec.id, self.rv, cancel_reason="无需校准")
        self.assertEqual(rec.status, STATUS_CANCELLED)

        undo_rec = self.svc.undo_last_transition(rec.id, self.rv)
        self.assertEqual(undo_rec.status, STATUS_COMPLETED)
        self.assertEqual(undo_rec.result, "合格")

    def test_archived_cannot_cancel_and_no_undo(self):
        rec = self._make_plan("T-005")
        self.svc.submit_calibration(
            rec.id, self.op, actual_date=_today_str(), result="合格")
        self.svc.send_for_review(rec.id, self.op)
        self.svc.review_archive(
            rec.id, self.rv, review_comment="流程合规")

        rec = self.storage.get_record_by_id(rec.id)
        self.assertEqual(rec.status, STATUS_ARCHIVED)

        with self.assertRaises(ValidationError) as ctx:
            self.svc.cancel_record(rec.id, self.rv, cancel_reason="x")
        self.assertIn("归档", str(ctx.exception))

        last = self.svc.get_undoable_transition(rec.id)
        self.assertIsNone(last, "归档后不应有可撤销的流转（归档操作不可撤销）")

    def test_operator_cannot_undo(self):
        rec = self._make_plan("T-006")
        self.svc.cancel_record(rec.id, self.rv, cancel_reason="test")

        with self.assertRaises(ValidationError) as ctx:
            self.svc.undo_last_transition(rec.id, self.op)
        self.assertIn("无撤销权限", str(ctx.exception))

    def test_empty_cancel_reason_rejected(self):
        rec = self._make_plan("T-007")
        with self.assertRaises(ValidationError) as ctx:
            self.svc.cancel_record(rec.id, self.rv, cancel_reason="   ")
        self.assertIn("不能为空", str(ctx.exception))

    def test_operator_cannot_cancel(self):
        rec = self._make_plan("T-008")
        with self.assertRaises(ValidationError) as ctx:
            self.svc.cancel_record(rec.id, self.op, cancel_reason="test")
        self.assertIn("无撤销权限", str(ctx.exception))

    def test_no_undoable_transition_rejected(self):
        rec = self._make_plan("T-009")
        with self.assertRaises(ValidationError) as ctx:
            self.svc.undo_last_transition(rec.id, self.rv)
        self.assertIn("无可撤销的流转操作", str(ctx.exception))

    def test_history_persistence_after_reload(self):
        rec = self._make_plan("T-010")
        self.svc.cancel_record(rec.id, self.rv, cancel_reason="测试持久化")
        self.svc.undo_last_transition(rec.id, self.rv)

        history_before = self.svc.list_history(rec.id)
        self.assertEqual(len(history_before), 2)

        del self.storage
        del self.svc

        storage2 = Storage(self.data_dir)
        svc2 = CalibrationService(storage2)

        history_after = svc2.list_history(rec.id)
        self.assertEqual(len(history_after), 2)
        self.assertEqual(history_after[0].action, ACTION_CANCEL)
        self.assertTrue(history_after[0].is_undone)
        self.assertEqual(history_after[1].action, ACTION_UNDO)

        rec_reloaded = storage2.get_record_by_id(rec.id)
        self.assertEqual(rec_reloaded.status, STATUS_PENDING)

    def test_instrument_calibration_date_rollback_on_undo(self):
        today = date.today()
        last_cal = (today - timedelta(days=400)).isoformat()
        new_cal = _today_str()

        inst = self.svc.create_instrument(
            code="T-011", name="回溯测试仪器",
            cycle_days=365,
            last_calibration_date=last_cal
        )
        self.svc.generate_plans()
        rec = self.svc.list_records(STATUS_PENDING)[0]

        rec = self.svc.submit_calibration(
            rec.id, self.op, actual_date=new_cal, result="合格",
            overdue_reason="送样延迟")

        inst_after = self.storage.get_instrument_by_id(inst.id)
        self.assertEqual(inst_after.last_calibration_date, new_cal)

        self.svc.undo_last_transition(rec.id, self.rv)

        inst_rolled = self.storage.get_instrument_by_id(inst.id)
        self.assertEqual(inst_rolled.last_calibration_date, last_cal,
                         "撤销录入校准后，仪器上次校准日期应回滚")

    def test_export_includes_cancelled_records(self):
        rec = self._make_plan("T-012")
        self.svc.cancel_record(rec.id, self.rv, cancel_reason="导出测试")

        csv_path = os.path.join(self.data_dir, "test_export.csv")
        n = self.svc.export_csv(csv_path)
        self.assertGreaterEqual(n, 1)

        with open(csv_path, "r", encoding="utf-8-sig") as f:
            content = f.read()
        self.assertIn(STATUS_CANCELLED, content)
        self.assertIn("导出测试", content)
        self.assertIn(rec.instrument_code, content)

    def test_undo_is_not_cancel(self):
        rec = self._make_plan("T-013")
        rec = self.svc.submit_calibration(
            rec.id, self.op, actual_date=_today_str(), result="合格")

        undo_rec = self.svc.undo_last_transition(rec.id, self.rv)

        self.assertNotEqual(undo_rec.status, STATUS_CANCELLED,
                            "撤销流转不等于取消记录")
        self.assertEqual(undo_rec.cancel_reason, "",
                         "撤销操作不应写入取消原因字段")

        history = self.svc.list_history(rec.id)
        self.assertIn(ACTION_UNDO, [h.action for h in history])
        self.assertNotIn(ACTION_CANCEL, [h.action for h in history],
                         "撤销流转没有产生取消动作的历史")

    def test_cancelled_list_uses_main_records(self):
        rec1 = self._make_plan("T-A")
        rec2 = self._make_plan("T-B")

        self.svc.cancel_record(rec1.id, self.rv, cancel_reason="取消A")

        cancelled = self.svc.list_cancelled_records()
        self.assertEqual(len(cancelled), 1)
        self.assertEqual(cancelled[0].instrument_code, "T-A")
        self.assertEqual(cancelled[0].cancel_reason, "取消A")

        self.svc.undo_last_transition(rec1.id, self.rv)
        cancelled = self.svc.list_cancelled_records()
        self.assertEqual(len(cancelled), 0)


def run_all():
    print("=" * 65)
    print(" 仪器校准排程系统 - 流转历史与撤销功能 自动化测试")
    print("=" * 65 + "\n")

    loader = unittest.TestLoader()
    suite = loader.loadTestsFromTestCase(TestTransitionHistory)
    runner = unittest.TextTestRunner(verbosity=2, stream=sys.stdout)
    result = runner.run(suite)

    print("\n" + "=" * 65)
    if result.wasSuccessful():
        print(f"全部 {result.testsRun} 个测试通过 [OK]")
    else:
        print(f"测试失败: {len(result.failures)} 失败, {len(result.errors)} 错误")
    print("=" * 65)

    return result.wasSuccessful()


if __name__ == "__main__":
    success = run_all()
    sys.exit(0 if success else 1)
