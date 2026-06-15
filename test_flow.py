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
    ValidationError, StorageError, _today_str, parse_date,
    STATUS_RULES, ACTION_RULES, get_available_actions, get_status_info, get_action_info
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

    def test_archived_cannot_cancel(self):
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
        self.assertIsNotNone(last, "归档后应有可撤销的流转（撤销归档）")
        self.assertEqual(last.action, ACTION_REVIEW_ARCHIVE)

    def test_archive_then_undo(self):
        rec = self._make_plan("T-010")
        self.svc.submit_calibration(
            rec.id, self.op, actual_date=_today_str(), result="合格",
            certificate_summary="CERT-001")
        self.svc.send_for_review(rec.id, self.op)
        self.svc.review_archive(
            rec.id, self.rv, review_comment="结果合格，同意归档")

        rec = self.storage.get_record_by_id(rec.id)
        self.assertEqual(rec.status, STATUS_ARCHIVED)
        self.assertIsNotNone(rec.archived_at)
        self.assertEqual(rec.reviewer, self.rv.username)
        self.assertEqual(rec.review_comment, "结果合格，同意归档")

        undo_rec = self.svc.undo_last_transition(rec.id, self.rv)
        self.assertEqual(undo_rec.status, STATUS_REVIEWING)
        self.assertIsNone(undo_rec.archived_at)
        self.assertEqual(undo_rec.reviewer, "")
        self.assertEqual(undo_rec.review_comment, "")
        self.assertEqual(undo_rec.certificate_summary, "CERT-001")
        self.assertEqual(undo_rec.result, "合格")

        history = self.storage.get_history_for_record(rec.id)
        self.assertEqual(len(history), 4)
        self.assertEqual(history[0].action, ACTION_SUBMIT)
        self.assertEqual(history[1].action, ACTION_SEND_REVIEW)
        self.assertEqual(history[2].action, ACTION_REVIEW_ARCHIVE)
        self.assertTrue(history[2].is_undone)
        self.assertEqual(history[3].action, ACTION_UNDO)

        last = self.svc.get_undoable_transition(rec.id)
        self.assertIsNotNone(last, "撤销归档后，最近可撤销提交复核")
        self.assertEqual(last.action, ACTION_SEND_REVIEW)

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
        self.assertIn("无取消权限", str(ctx.exception))

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


class TestTransitionSummary(unittest.TestCase):
    def setUp(self):
        self.data_dir = fresh_data_dir()
        self.storage = Storage(self.data_dir)
        self.svc = CalibrationService(self.storage)
        self.op, self.rv = make_users(self.storage)

    def tearDown(self):
        if os.path.exists(self.data_dir):
            shutil.rmtree(self.data_dir)

    def _make_plan(self, code: str = "T-S001"):
        make_test_instrument(self.svc, code)
        plans = self.svc.generate_plans()
        matching = [p for p in plans if p.instrument_code == code]
        self.assertGreaterEqual(len(matching), 1, f"没有找到仪器 {code} 的计划")
        return matching[0]

    def test_status_rules_defined_for_all_statuses(self):
        for s in [STATUS_PENDING, STATUS_COMPLETED, STATUS_REVIEWING,
                  STATUS_ARCHIVED, STATUS_CANCELLED]:
            self.assertIn(s, STATUS_RULES, f"STATUS_RULES 中缺少 {s} 的定义")
            info = get_status_info(s)
            self.assertTrue(info.get("description"), f"{s} 缺少 description")
            self.assertTrue(info.get("how_got_here"), f"{s} 缺少 how_got_here")
            self.assertTrue(info.get("color"), f"{s} 缺少 color")

    def test_action_rules_defined_for_all_actions(self):
        for a in [ACTION_SUBMIT, ACTION_SEND_REVIEW, ACTION_REVIEW_ARCHIVE,
                  ACTION_CANCEL, ACTION_UNDO]:
            self.assertIn(a, ACTION_RULES, f"ACTION_RULES 中缺少 {a} 的定义")
            info = get_action_info(a)
            self.assertTrue(info.get("description"), f"{a} 缺少 description")
            self.assertTrue(info.get("from_statuses"), f"{a} 缺少 from_statuses")

    def test_get_available_actions_pending(self):
        actions_op = get_available_actions(STATUS_PENDING, ROLE_OPERATOR)
        action_keys = [a["action"] for a in actions_op]
        self.assertIn(ACTION_SUBMIT, action_keys, "待执行状态下操作员应可录入校准")
        self.assertIn(ACTION_CANCEL, action_keys, "待执行状态下列表应包含取消记录（带权限提示）")
        cancel_info = [a for a in actions_op if a["action"] == ACTION_CANCEL][0]
        self.assertFalse(cancel_info["can_do"], "操作员不应有取消权限")
        self.assertTrue(cancel_info["role_missing"], "取消记录应标记为角色缺失")

        actions_rv = get_available_actions(STATUS_PENDING, ROLE_REVIEWER)
        cancel_rv = [a for a in actions_rv if a["action"] == ACTION_CANCEL][0]
        self.assertTrue(cancel_rv["can_do"], "复核员应有取消权限")
        self.assertFalse(cancel_rv["role_missing"])

    def test_get_available_actions_archived(self):
        actions = get_available_actions(STATUS_ARCHIVED, ROLE_REVIEWER)
        self.assertEqual(len(actions), 0, "归档状态下无直接可执行的流转操作")

    def test_get_available_actions_reviewing(self):
        actions_op = get_available_actions(STATUS_REVIEWING, ROLE_OPERATOR)
        review_action = [a for a in actions_op if a["action"] == ACTION_REVIEW_ARCHIVE]
        self.assertTrue(review_action, "待复核状态下列表应包含复核归档（带权限提示）")
        self.assertFalse(review_action[0]["can_do"], "操作员不应有复核权限")
        self.assertEqual(review_action[0]["to_status"], STATUS_ARCHIVED)

        actions_rv = get_available_actions(STATUS_REVIEWING, ROLE_REVIEWER)
        review_rv = [a for a in actions_rv if a["action"] == ACTION_REVIEW_ARCHIVE][0]
        self.assertTrue(review_rv["can_do"], "复核员应有复核归档权限")

    def test_transition_summary_pending_initial(self):
        rec = self._make_plan("T-S002")
        summary = self.svc.get_transition_summary(rec.id, self.op)
        self.assertEqual(summary["current_status"], STATUS_PENDING)
        self.assertEqual(summary["history_count"], 0)
        self.assertEqual(summary["undo_count"], 0)
        self.assertIsNone(summary["undo_info"])
        self.assertIn("生成校准计划", summary["why_here"])
        action_keys = [a["action"] for a in summary["available_actions"]]
        self.assertIn(ACTION_SUBMIT, action_keys)

    def test_transition_summary_after_submit(self):
        rec = self._make_plan("T-S003")
        self.svc.submit_calibration(rec.id, self.op,
                                    actual_date=_today_str(), result="合格")
        summary_op = self.svc.get_transition_summary(rec.id, self.op)
        self.assertEqual(summary_op["current_status"], STATUS_COMPLETED)
        self.assertEqual(summary_op["history_count"], 1)
        self.assertIsNotNone(summary_op["undo_info"], "录入校准后应有可撤销操作")
        self.assertEqual(summary_op["undo_info"]["action"], ACTION_SUBMIT)
        self.assertEqual(summary_op["undo_info"]["undo_returns_to_status"], STATUS_PENDING)
        self.assertFalse(summary_op["undo_info"]["can_do"], "操作员不应能撤销")
        self.assertTrue(summary_op["undo_info"]["undo_role_missing"])
        action_keys = [a["action"] for a in summary_op["available_actions"]]
        self.assertIn(ACTION_SEND_REVIEW, action_keys)

        summary_rv = self.svc.get_transition_summary(rec.id, self.rv)
        self.assertTrue(summary_rv["undo_info"]["can_do"], "复核员应能撤销")
        self.assertFalse(summary_rv["undo_info"]["undo_role_missing"])

    def test_transition_summary_after_archive(self):
        rec = self._make_plan("T-S004")
        self.svc.submit_calibration(rec.id, self.op,
                                    actual_date=_today_str(), result="合格")
        self.svc.send_for_review(rec.id, self.op)
        self.svc.review_archive(rec.id, self.rv, review_comment="流程合规")

        summary = self.svc.get_transition_summary(rec.id, self.rv)
        self.assertEqual(summary["current_status"], STATUS_ARCHIVED)
        self.assertEqual(summary["history_count"], 3)
        self.assertEqual(summary["undo_count"], 0)
        self.assertIsNotNone(summary["undo_info"])
        self.assertEqual(summary["undo_info"]["action"], ACTION_REVIEW_ARCHIVE)
        self.assertEqual(summary["undo_info"]["undo_returns_to_status"], STATUS_REVIEWING)
        self.assertEqual(len(summary["available_actions"]), 0,
                         "归档状态下无直接流转动作，只能撤销")

    def test_transition_summary_after_cancel(self):
        rec = self._make_plan("T-S005")
        self.svc.cancel_record(rec.id, self.rv, cancel_reason="无需校准")

        summary = self.svc.get_transition_summary(rec.id, self.rv)
        self.assertEqual(summary["current_status"], STATUS_CANCELLED)
        self.assertIsNotNone(summary["undo_info"])
        self.assertEqual(summary["undo_info"]["action"], ACTION_CANCEL)
        self.assertEqual(summary["undo_info"]["undo_returns_to_status"], STATUS_PENDING,
                         "撤销取消记录应回到待执行状态")
        self.assertIn("无需校准", summary["undo_info"]["reason"])

    def test_cancel_vs_undo_distinction_in_summary(self):
        rec1 = self._make_plan("T-S006")
        self.svc.submit_calibration(rec1.id, self.op,
                                    actual_date=_today_str(), result="合格")
        self.svc.cancel_record(rec1.id, self.rv, cancel_reason="取消这条")
        summary_cancel = self.svc.get_transition_summary(rec1.id, self.rv)
        self.assertEqual(summary_cancel["current_status"], STATUS_CANCELLED)
        self.assertIn(STATUS_CANCELLED, summary_cancel["why_here"])
        self.assertIn("取消记录", summary_cancel["undo_info"]["action"])

        rec2 = self._make_plan("T-S007")
        self.svc.submit_calibration(rec2.id, self.op,
                                    actual_date=_today_str(), result="合格")
        self.svc.undo_last_transition(rec2.id, self.rv)
        summary_undo = self.svc.get_transition_summary(rec2.id, self.rv)
        self.assertEqual(summary_undo["current_status"], STATUS_PENDING)
        self.assertEqual(summary_undo["history_count"], 2,
                         "撤销操作也应记录为一条历史（共2条：录入+撤销）")
        self.assertIn("撤销流转", summary_undo["why_here"])
        self.assertNotEqual(summary_undo["current_status"], STATUS_CANCELLED,
                            "撤销流转不应让记录进入取消状态")

    def test_summary_persistence_after_reload(self):
        rec = self._make_plan("T-S008")
        self.svc.submit_calibration(rec.id, self.op,
                                    actual_date=_today_str(), result="合格")
        self.svc.send_for_review(rec.id, self.op)

        summary_before = self.svc.get_transition_summary(rec.id, self.rv)

        del self.storage
        del self.svc

        storage2 = Storage(self.data_dir)
        svc2 = CalibrationService(storage2)
        rv2 = [u for u in storage2.load_users() if u.role == ROLE_REVIEWER][0]

        summary_after = svc2.get_transition_summary(rec.id, rv2)

        self.assertEqual(summary_before["current_status"], summary_after["current_status"])
        self.assertEqual(summary_before["history_count"], summary_after["history_count"])
        self.assertEqual(summary_before["undo_count"], summary_after["undo_count"])
        self.assertEqual(summary_before["undo_info"]["action"],
                         summary_after["undo_info"]["action"])
        self.assertEqual(summary_before["undo_info"]["undo_returns_to_status"],
                         summary_after["undo_info"]["undo_returns_to_status"])
        actions_before = [a["action"] for a in summary_before["available_actions"]]
        actions_after = [a["action"] for a in summary_after["available_actions"]]
        self.assertListEqual(actions_before, actions_after,
                             "重启后可用动作应保持一致")

    def test_export_csv_matches_summary(self):
        rec = self._make_plan("T-S009")
        self.svc.submit_calibration(rec.id, self.op,
                                    actual_date=_today_str(), result="合格",
                                    certificate_summary="CERT-EXPORT-001")
        self.svc.send_for_review(rec.id, self.op)

        summary = self.svc.get_transition_summary(rec.id, self.rv)

        csv_path = os.path.join(self.data_dir, "summary_export_test.csv")
        self.svc.export_csv(csv_path)

        with open(csv_path, "r", encoding="utf-8-sig") as f:
            content = f.read()

        self.assertIn(rec.instrument_code, content)
        self.assertIn(summary["current_status_info"]["description"], content,
                      "CSV导出应包含状态说明，与界面摘要共用同一来源")
        self.assertIn(summary["why_here"], content,
                      "CSV导出应包含为什么在这的说明")
        self.assertIn(str(summary["history_count"]), content)
        self.assertIn(summary["undo_info"]["action"], content,
                      "CSV导出应包含最近可撤销操作")
        self.assertIn(summary["undo_info"]["undo_returns_to_status"], content,
                      "CSV导出应包含撤销返回状态")

    def test_export_html_matches_summary(self):
        rec = self._make_plan("T-S010")
        self.svc.submit_calibration(rec.id, self.op,
                                    actual_date=_today_str(), result="合格")
        self.svc.send_for_review(rec.id, self.op)
        self.svc.review_archive(rec.id, self.rv, review_comment="测试导出一致性")

        summary = self.svc.get_transition_summary(rec.id, self.rv)

        html_path = os.path.join(self.data_dir, "summary_export_test.html")
        self.svc.export_html(html_path)

        with open(html_path, "r", encoding="utf-8") as f:
            content = f.read()

        self.assertIn(rec.instrument_code, content)
        self.assertIn(summary["current_status_info"]["description"], content,
                      "HTML导出应包含状态说明，与界面摘要共用同一来源")
        self.assertIn(summary["why_here"], content,
                      "HTML导出应包含为什么在这的说明")
        self.assertIn(str(summary["history_count"]), content)
        self.assertIn("审计链路说明", content,
                      "HTML导出应包含审计链路说明章节")
        self.assertIn("流转统计总览", content,
                      "HTML导出应包含统计总览")
        self.assertIn("归档", content, "HTML导出应包含统计卡片")

    def test_operator_reviewer_permission_diff_in_summary(self):
        rec = self._make_plan("T-S011")
        self.svc.submit_calibration(rec.id, self.op,
                                    actual_date=_today_str(), result="合格")
        self.svc.send_for_review(rec.id, self.op)

        s_op = self.svc.get_transition_summary(rec.id, self.op)
        s_rv = self.svc.get_transition_summary(rec.id, self.rv)

        review_action_op = [a for a in s_op["available_actions"]
                            if a["action"] == ACTION_REVIEW_ARCHIVE][0]
        self.assertFalse(review_action_op["can_do"], "操作员不能复核归档")
        self.assertTrue(review_action_op["role_missing"])

        review_action_rv = [a for a in s_rv["available_actions"]
                            if a["action"] == ACTION_REVIEW_ARCHIVE][0]
        self.assertTrue(review_action_rv["can_do"], "复核员可以复核归档")
        self.assertFalse(review_action_rv["role_missing"])

        self.assertFalse(s_op["undo_info"]["can_do"], "操作员不能撤销")
        self.assertTrue(s_op["undo_info"]["undo_role_missing"])
        self.assertTrue(s_rv["undo_info"]["can_do"], "复核员可以撤销")

    def test_archive_then_undo_summary_consistency(self):
        rec = self._make_plan("T-S012")
        self.svc.submit_calibration(rec.id, self.op,
                                    actual_date=_today_str(), result="合格")
        self.svc.send_for_review(rec.id, self.op)
        self.svc.review_archive(rec.id, self.rv, review_comment="准备撤销归档")

        s_before = self.svc.get_transition_summary(rec.id, self.rv)
        self.assertEqual(s_before["current_status"], STATUS_ARCHIVED)
        self.assertEqual(s_before["undo_info"]["action"], ACTION_REVIEW_ARCHIVE)
        self.assertEqual(s_before["undo_info"]["undo_returns_to_status"], STATUS_REVIEWING)

        self.svc.undo_last_transition(rec.id, self.rv)

        s_after = self.svc.get_transition_summary(rec.id, self.rv)
        self.assertEqual(s_after["current_status"], STATUS_REVIEWING,
                         "撤销归档后应回到待复核状态")
        self.assertEqual(s_after["undo_count"], 1,
                         "撤销后undo_count应加1")
        self.assertEqual(s_after["history_count"], 4,
                         "撤销归档后共4条历史：录入→提交→归档→撤销归档")
        self.assertIsNotNone(s_after["undo_info"],
                             "撤销归档后仍然可以继续撤销提交复核")
        self.assertEqual(s_after["undo_info"]["action"], ACTION_SEND_REVIEW)
        self.assertEqual(s_after["undo_info"]["undo_returns_to_status"], STATUS_COMPLETED)


def run_all():
    print("=" * 70)
    print(" 仪器校准排程系统 - 流转历史/撤销/摘要/权限/导出 自动化测试")
    print("=" * 70 + "\n")

    loader = unittest.TestLoader()
    suite = unittest.TestSuite()
    suite.addTests(loader.loadTestsFromTestCase(TestTransitionHistory))
    suite.addTests(loader.loadTestsFromTestCase(TestTransitionSummary))
    runner = unittest.TextTestRunner(verbosity=2, stream=sys.stdout)
    result = runner.run(suite)

    print("\n" + "=" * 70)
    if result.wasSuccessful():
        print(f"全部 {result.testsRun} 个测试通过 [OK]")
    else:
        print(f"测试失败: {len(result.failures)} 失败, {len(result.errors)} 错误")
        if result.failures:
            print("\n失败详情:")
            for test, trace in result.failures:
                print(f"  - {test}: {trace[:200]}...")
        if result.errors:
            print("\n错误详情:")
            for test, trace in result.errors:
                print(f"  - {test}: {trace[:200]}...")
    print("=" * 70)

    return result.wasSuccessful()


if __name__ == "__main__":
    success = run_all()
    sys.exit(0 if success else 1)
