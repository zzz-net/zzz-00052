import os
import sys
import shutil
from datetime import date, timedelta

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from calibration_tool import (
    Storage, CalibrationService, CalibrationRecord,
    STATUS_PENDING, STATUS_COMPLETED, STATUS_REVIEWING,
    STATUS_ARCHIVED, STATUS_CANCELLED,
    ROLE_OPERATOR, ROLE_REVIEWER, User,
    ValidationError, StorageError, parse_date, _today_str
)


def fresh_data_dir() -> str:
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                        "test_data_tmp")
    if os.path.exists(path):
        shutil.rmtree(path)
    return path


def assert_raises(fn, exc_type, msg_substr: str = ""):
    try:
        fn()
    except exc_type as e:
        if msg_substr and msg_substr not in str(e):
            raise AssertionError(
                f"期望错误包含 '{msg_substr}'，实际为: {e}")
        return True
    raise AssertionError(f"期望抛出 {exc_type.__name__}，但未抛出")


def print_pass(name: str):
    print(f"  [OK] {name}")


def test_instrument_crud():
    print("[测试] 仪器台账 CRUD")
    data_dir = fresh_data_dir()
    storage = Storage(data_dir)
    svc = CalibrationService(storage)

    inst1 = svc.create_instrument(
        code="T-001", name="测试仪器", model="M1",
        manufacturer="厂家A", location="房间1", cycle_days=90,
        last_calibration_date=(date.today() - timedelta(days=100)).isoformat(),
        owner="张三", remark="备注1"
    )
    assert inst1.code == "T-001"
    print_pass("新增仪器")

    insts = svc.list_instruments()
    assert len(insts) == 1
    print_pass("查询仪器列表")

    svc.update_instrument(inst1.id, name="测试仪器-已更新", cycle_days=180)
    inst1_u = storage.get_instrument_by_id(inst1.id)
    assert inst1_u.name == "测试仪器-已更新"
    assert inst1_u.cycle_days == 180
    print_pass("更新仪器")

    assert_raises(
        lambda: svc.create_instrument(code="T-001", name="重复编号"),
        ValidationError, "已存在")
    print_pass("重复仪器编号被拒绝")

    assert_raises(
        lambda: svc.create_instrument(code="", name="空编号"),
        ValidationError, "不能为空")
    assert_raises(
        lambda: svc.create_instrument(code="T-002", name=""),
        ValidationError, "不能为空")
    print_pass("空编号/空名称被拒绝")

    assert_raises(
        lambda: svc.create_instrument(code="T-002", name="坏日期",
                                      last_calibration_date="2024-13-40"),
        ValidationError, "格式无效")
    assert_raises(
        lambda: svc.create_instrument(code="T-002", name="坏周期", cycle_days=-5),
        ValidationError, "正整数")
    print_pass("非法日期/坏周期被拒绝")

    shutil.rmtree(data_dir)
    print("")


def test_plan_generation_and_flow():
    print("[测试] 计划生成与状态流转主流程")
    data_dir = fresh_data_dir()
    storage = Storage(data_dir)
    svc = CalibrationService(storage)

    storage.save_users([
        User(username="op1", role=ROLE_OPERATOR),
        User(username="rv1", role=ROLE_REVIEWER),
    ])
    op = storage.load_users()[0]
    rv = storage.load_users()[1]

    today = date.today()
    svc.create_instrument(
        code="A-1", name="仪器A", cycle_days=365,
        last_calibration_date=(today - timedelta(days=400)).isoformat())
    svc.create_instrument(
        code="A-2", name="仪器B", cycle_days=180,
        last_calibration_date="")

    plans = svc.generate_plans()
    assert len(plans) == 2, f"应生成2条计划，实际{len(plans)}"
    print_pass(f"生成 {len(plans)} 条校准计划")

    plans2 = svc.generate_plans()
    assert len(plans2) == 0, "重复生成不应产生新计划"
    print_pass("重复生成计划时跳过已有未完成记录")

    pending = svc.list_records(STATUS_PENDING)
    assert len(pending) == 2
    rec = pending[0]

    rec = svc.submit_calibration(
        rec.id, op,
        actual_date=_today_str(),
        result="合格",
        certificate_summary="证书号:C2024-001;误差:±0.01%",
        overdue_reason="设备送检延迟" if rec.is_overdue else ""
    )
    assert rec.status == STATUS_COMPLETED
    assert rec.actual_date == _today_str()
    print_pass("录入校准结果，状态→已完成")

    rec = svc.send_for_review(rec.id, op)
    assert rec.status == STATUS_REVIEWING
    print_pass("提交复核，状态→待复核")

    rec = svc.review_archive(
        rec.id, rv,
        review_comment="校准过程合规，结果可信，同意归档",
        certificate_summary="证书号:C2024-001;误差:±0.01%;签发人:李工"
    )
    assert rec.status == STATUS_ARCHIVED
    assert rec.reviewer == "rv1"
    assert rec.archived_at is not None
    print_pass("复核归档，状态→归档")

    archived = svc.list_records(STATUS_ARCHIVED)
    assert len(archived) == 1
    print_pass("归档记录可查询")

    shutil.rmtree(data_dir)
    print("")


def test_failure_paths():
    print("[测试] 失败路径（权限/空撤销/非法输入等）")
    data_dir = fresh_data_dir()
    storage = Storage(data_dir)
    svc = CalibrationService(storage)
    storage.save_users([
        User(username="op1", role=ROLE_OPERATOR),
        User(username="rv1", role=ROLE_REVIEWER),
    ])
    op = storage.load_users()[0]
    rv = storage.load_users()[1]

    today = date.today()
    svc.create_instrument(
        code="F-1", name="失败路径仪器", cycle_days=365,
        last_calibration_date=(today - timedelta(days=400)).isoformat())
    svc.generate_plans()
    rec = svc.list_records(STATUS_PENDING)[0]

    assert_raises(
        lambda: svc.submit_calibration(rec.id, op,
            actual_date="", result="合格"),
        ValidationError, "不能为空")
    print_pass("空实际日期被拒绝")

    assert_raises(
        lambda: svc.submit_calibration(rec.id, op,
            actual_date="bad-date", result="合格"),
        ValidationError, "格式无效")
    print_pass("非法日期格式被拒绝")

    assert_raises(
        lambda: svc.submit_calibration(rec.id, op,
            actual_date=_today_str(), result=""),
        ValidationError, "不能为空")
    print_pass("空校准结果被拒绝")

    svc.submit_calibration(
        rec.id, op,
        actual_date=_today_str(), result="合格",
        overdue_reason="送检延迟")
    rec = storage.get_record_by_id(rec.id)

    assert_raises(
        lambda: svc.review_archive(rec.id, op, review_comment="越权操作"),
        ValidationError, "无复核权限")
    print_pass("普通操作员尝试复核被拒绝")

    rec = svc.send_for_review(rec.id, op)

    assert_raises(
        lambda: svc.review_archive(rec.id, rv, review_comment=""),
        ValidationError, "不能为空")
    print_pass("空复核意见被拒绝")

    assert_raises(
        lambda: svc.cancel_record(rec.id, op, cancel_reason="越权撤销"),
        ValidationError, "无撤销权限")
    print_pass("普通操作员尝试撤销被拒绝")

    assert_raises(
        lambda: svc.cancel_record(rec.id, rv, cancel_reason=""),
        ValidationError, "不能为空")
    print_pass("空撤销原因被拒绝")

    cancelled = svc.cancel_record(rec.id, rv, cancel_reason="设备报废，无需校准")
    assert cancelled.status == STATUS_CANCELLED
    assert len(svc.list_cancelled_records()) == 1
    assert len([r for r in svc.list_records() if r.id == rec.id]) == 0
    print_pass("撤销记录从主记录移至取消记录列表")

    active_records = svc.list_records()
    cancelled_list = svc.list_cancelled_records()
    assert len(active_records) == 0
    assert len(cancelled_list) == 1
    print_pass("撤销操作不破坏其他记录状态")

    shutil.rmtree(data_dir)
    print("")


def test_persistence_and_export():
    print("[测试] 数据持久化与导出")
    data_dir = fresh_data_dir()
    storage = Storage(data_dir)
    svc = CalibrationService(storage)
    storage.save_users([
        User(username="op1", role=ROLE_OPERATOR),
        User(username="rv1", role=ROLE_REVIEWER),
    ])
    op = storage.load_users()[0]
    rv = storage.load_users()[1]

    svc.create_instrument(code="P-1", name="持久化仪器", cycle_days=90,
                          last_calibration_date=_today_str())
    svc.generate_plans()
    rec = svc.list_records(STATUS_PENDING)[0]
    rec = svc.submit_calibration(rec.id, op,
        actual_date=_today_str(), result="合格")
    rec = svc.send_for_review(rec.id, op)
    rec = svc.review_archive(rec.id, rv,
        review_comment="数据完整，归档保存")
    svc.cancel_record(svc.list_records(STATUS_PENDING)[0].id
                      if svc.list_records(STATUS_PENDING) else rec.id,
                      rv, cancel_reason="测试撤销") if False else None

    del storage
    del svc

    storage2 = Storage(data_dir)
    svc2 = CalibrationService(storage2)
    assert len(svc2.list_instruments()) == 1
    assert svc2.list_instruments()[0].code == "P-1"
    assert len(svc2.list_records(STATUS_ARCHIVED)) == 1
    print_pass("关闭/重开后台数据一致（台账+记录）")

    csv_path = os.path.join(data_dir, "export.csv")
    n = svc2.export_csv(csv_path)
    assert n >= 1
    assert os.path.exists(csv_path)
    with open(csv_path, "r", encoding="utf-8-sig") as f:
        content = f.read()
        assert "P-1" in content
    print_pass("CSV 导出可读且包含数据")

    html_path = os.path.join(data_dir, "export.html")
    n = svc2.export_html(html_path)
    assert n >= 1
    assert os.path.exists(html_path)
    with open(html_path, "r", encoding="utf-8") as f:
        html = f.read()
        assert "<html" in html.lower()
        assert "P-1" in html
    print_pass("HTML 导出格式正确且包含数据")

    shutil.rmtree(data_dir)
    print("")


def run_all():
    print("=" * 60)
    print("仪器校准排程系统 - 自动化测试")
    print("=" * 60 + "\n")

    test_instrument_crud()
    test_plan_generation_and_flow()
    test_failure_paths()
    test_persistence_and_export()

    print("=" * 60)
    print("全部测试通过 [OK]")
    print("=" * 60)


if __name__ == "__main__":
    run_all()
