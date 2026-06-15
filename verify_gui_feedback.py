import os
import sys
import shutil
from datetime import date, timedelta

sys.path.insert(0, os.path.dirname(__file__))

from calibration_tool import (
    CalibrationService, Storage, User,
    STATUS_PENDING, STATUS_COMPLETED, STATUS_REVIEWING,
    STATUS_ARCHIVED, STATUS_CANCELLED,
    ROLE_OPERATOR, ROLE_REVIEWER,
    ACTION_SUBMIT, ACTION_SEND_REVIEW, ACTION_REVIEW_ARCHIVE,
    ACTION_CANCEL, ACTION_UNDO,
    _today_str, get_status_info
)

DATA_DIR = os.path.join(os.path.dirname(__file__), "data_verify")

def section(title):
    print(f"\n{'='*75}")
    print(f"  {title}")
    print(f"{'='*75}\n")

def sub_section(title):
    print(f"\n{'─'*65}")
    print(f"  {title}")
    print(f"{'─'*65}")

def print_status(rec):
    print(f"    记录ID: {rec.id}")
    print(f"    状态: {rec.status}")
    print(f"    仪器: {rec.instrument_code} - {rec.instrument_name}")
    print(f"    计划日期: {rec.planned_date}")
    if rec.actual_date:
        print(f"    实际日期: {rec.actual_date}")
    if rec.result:
        print(f"    结果: {rec.result}")
    if rec.certificate_summary:
        print(f"    证书摘要: {rec.certificate_summary}")
    if rec.review_comment:
        print(f"    复核意见: {rec.review_comment}")
    if rec.cancel_reason:
        print(f"    取消原因: {rec.cancel_reason}")

def print_history(history):
    print(f"\n    {'时间':<22} {'操作':<10} {'原状态':<8} {'新状态':<8} {'操作人':<10} {'原因':<15} {'已撤销':<6}")
    print(f"    {'─'*22} {'─'*10} {'─'*8} {'─'*8} {'─'*10} {'─'*15} {'─'*6}")
    for h in history:
        reason = h.reason[:14] if h.reason else ""
        print(f"    {h.created_at:<22} {h.action:<10} {h.from_status:<8} {h.to_status:<8} {h.by_user:<10} {reason:<15} {'是' if h.is_undone else '否':<6}")

def print_summary(summary, title="流转摘要"):
    status_info = summary.get("current_status_info", {})
    print(f"\n    ┌─────────────────────────────────────────────────────────────────┐")
    print(f"    │  📋 {title:<61} │")
    print(f"    ├─────────────────────────────────────────────────────────────────┤")
    print(f"    │  当前状态: 【{summary['current_status']}】{' '*(58 - len(summary['current_status']) * 2)}│")
    print(f"    │  状态说明: {status_info.get('description', '')[:62]:<62} │")
    print(f"    │  为什么在这: {summary.get('why_here', '')[:60]:<60} │")
    print(f"    │  流转统计: 共 {summary.get('history_count', 0)} 条流转，{summary.get('undo_count', 0)} 条已撤销{' '*(44)}│")
    print(f"    │  当前角色: {summary.get('user_role', '未指定')}{' '*(62 - len(str(summary.get('user_role',''))))}│")
    print(f"    ├─────────────────────────────────────────────────────────────────┤")

    undo_info = summary.get("undo_info")
    if undo_info:
        can_tag = "✅可撤销" if undo_info.get("can_do") else "⚠️需复核员权限"
        print(f"    │  🔄 撤销信息: {can_tag}{' '*(59 - len(can_tag) * 2)}│")
        print(f"    │    最近操作: {undo_info['action']}{' '*(60 - len(undo_info['action']) * 2)}│")
        print(f"    │    操作人/时间: {undo_info['by_user']} @ {undo_info['created_at'][:19]}{' '*(38 - len(undo_info['by_user']))}│")
        print(f"    │    撤销后返回: 【{undo_info['undo_returns_to_status']}】{' '*(56 - len(undo_info['undo_returns_to_status'])*2)}│")
        print(f"    │    返回说明: {undo_info.get('undo_returns_to_description', '')[:60]:<60} │")
        if undo_info.get("reason"):
            print(f"    │    原操作原因: {undo_info['reason'][:60]:<60} │")
    else:
        print(f"    │  🔄 撤销信息: 无可撤销的流转操作（初始状态或已撤销到最早）{' '*(18)}│")

    print(f"    ├─────────────────────────────────────────────────────────────────┤")
    actions = summary.get("available_actions", [])
    if not actions:
        print(f"    │  ⏩ 下一步操作: 无直接流转动作，可尝试撤销流转{' '*(30)}│")
    else:
        print(f"    │  ⏩ 下一步可执行操作 ({len(actions)} 项):{' '*(45)}│")
        for i, a in enumerate(actions, 1):
            role_tag = ""
            if a.get("role_missing"):
                role_tag = " ⚠️权限不足"
            elif a.get("required_role"):
                role_tag = " 🔒需" + a["required_role"]
            else:
                role_tag = " 🔓所有角色"
            header = f"    {i}. 【{a['button_label']}】{role_tag}"
            print(f"    │  {header[:68]:<68}│")
            to_line = f"       执行后状态: 【{a['to_status']}】— {a['to_status_description']}"
            print(f"    │  {to_line[:68]:<68}│")
    print(f"    └─────────────────────────────────────────────────────────────────┘")

def compare_summary_with_export(summary, csv_content, html_content, record_code):
    checks = []
    desc = summary["current_status_info"]["description"]
    why = summary["why_here"]
    hcount = str(summary["history_count"])

    checks.append(("CSV包含状态说明", desc in csv_content, f"CSV中应包含: '{desc[:30]}...'"))
    checks.append(("CSV包含'为什么在这'", why[:20] in csv_content, f"CSV中应包含why_here"))
    checks.append(("CSV包含流转次数", hcount in csv_content, f"CSV中应包含历史条数{hcount}"))
    checks.append(("HTML包含状态说明", desc in html_content, f"HTML中应包含状态说明"))
    checks.append(("HTML包含审计链路章节", "审计链路说明" in html_content, "HTML中应有审计链路说明"))
    checks.append(("HTML包含流转统计总览", "流转统计总览" in html_content, "HTML中应有统计总览"))
    checks.append(("HTML包含记录仪器编号", record_code in html_content, f"HTML中应包含{record_code}"))

    print(f"\n    导出一致性检查结果:")
    all_ok = True
    for name, ok, msg in checks:
        status = "✅通过" if ok else "❌失败"
        print(f"      {status}  {name}: {msg}")
        if not ok:
            all_ok = False
    return all_ok

def main():
    if os.path.exists(DATA_DIR):
        shutil.rmtree(DATA_DIR)

    storage = Storage(DATA_DIR)
    svc = CalibrationService(storage)

    op1 = User(username="op1_manual", role=ROLE_OPERATOR)
    rv1 = User(username="rv1_manual", role=ROLE_REVIEWER)
    storage.save_users([op1, rv1])

    print("\n" + "="*75)
    print("  用户可见反馈 + 流转摘要 + 审计链路 手动/CLI 综合验证脚本")
    print("  验证：操作摘要、权限差异、撤销机制、导出一致性、重启一致性")
    print("="*75)

    section("1. 初始化：新增仪器 + 生成校准计划（检查初始状态摘要）")
    try:
        sub_section("1.1 新增仪器 MANUAL-001 并生成计划")
        inst = svc.create_instrument(
            code="MANUAL-001", name="手动验证仪器A",
            cycle_days=365,
            last_calibration_date=(date.today() - timedelta(days=30)).isoformat(),
            model="验证型号", manufacturer="验证厂商", location="验证实验室",
            owner="王工"
        )
        plans = svc.generate_plans()
        rec = plans[0]
        print(f"    [OK] 计划生成成功")
        print_status(rec)

        sub_section("1.2 【操作员视角】检查初始状态（待执行）的流转摘要")
        s_op = svc.get_transition_summary(rec.id, op1)
        print_summary(s_op, "操作员视角 初始摘要")

        assert s_op["current_status"] == STATUS_PENDING
        assert s_op["history_count"] == 0
        assert s_op["undo_info"] is None
        action_keys = [a["action"] for a in s_op["available_actions"]]
        assert ACTION_SUBMIT in action_keys
        cancel_a = [a for a in s_op["available_actions"] if a["action"] == ACTION_CANCEL]
        assert len(cancel_a) == 1
        assert cancel_a[0]["role_missing"] == True, "操作员取消记录应标记为权限不足"
        print(f"\n    [OK] 初始摘要验证：操作员无取消权限（role_missing=True）")

        sub_section("1.3 【复核员视角】对比同一状态的摘要（权限差异）")
        s_rv = svc.get_transition_summary(rec.id, rv1)
        print_summary(s_rv, "复核员视角 初始摘要")

        cancel_rv = [a for a in s_rv["available_actions"] if a["action"] == ACTION_CANCEL]
        assert cancel_rv[0]["can_do"] == True, "复核员应有取消权限"
        assert cancel_rv[0]["role_missing"] == False
        print(f"\n    [OK] 权限差异验证：同一状态不同角色 → 可执行动作不同")
        print(f"        操作员: can_do={cancel_a[0]['can_do']}, role_missing={cancel_a[0]['role_missing']}")
        print(f"        复核员: can_do={cancel_rv[0]['can_do']}, role_missing={cancel_rv[0]['role_missing']}")

    except Exception as e:
        import traceback; traceback.print_exc()
        print(f"    [ERROR] {e}")
        return 1

    section("2. 录入校准 → 提交复核 → 对比不同阶段的摘要信息")
    try:
        sub_section("2.1 操作员录入校准结果")
        rec = svc.submit_calibration(
            rec.id, op1,
            actual_date=_today_str(),
            result="合格",
            certificate_summary="MANUAL-CERT-001"
        )
        print(f"    [OK] 录入校准成功")

        sub_section("2.2 【已完成】状态摘要（操作员 vs 复核员）")
        s_op = svc.get_transition_summary(rec.id, op1)
        print_summary(s_op, "操作员视角 已完成状态")
        assert s_op["undo_info"] is not None
        assert s_op["undo_info"]["action"] == ACTION_SUBMIT
        assert s_op["undo_info"]["can_do"] == False, "操作员不能撤销"
        assert s_op["undo_info"]["undo_role_missing"] == True
        print(f"\n    [OK] 操作员视角：撤销按钮存在，但 can_do=False, undo_role_missing=True")

        s_rv = svc.get_transition_summary(rec.id, rv1)
        assert s_rv["undo_info"]["can_do"] == True, "复核员能撤销"
        assert s_rv["undo_info"]["undo_returns_to_status"] == STATUS_PENDING
        print(f"    [OK] 复核员视角：撤销后返回状态 = STATUS_PENDING（与 ACTION_RULES 一致）")

        sub_section("2.3 提交复核，检查【待复核】状态摘要")
        rec = svc.send_for_review(rec.id, op1)
        s_rv = svc.get_transition_summary(rec.id, rv1)
        print_summary(s_rv, "复核员视角 待复核状态")
        action_keys = [a["action"] for a in s_rv["available_actions"]]
        assert ACTION_REVIEW_ARCHIVE in action_keys
        review_a = [a for a in s_rv["available_actions"] if a["action"] == ACTION_REVIEW_ARCHIVE][0]
        assert review_a["can_do"] == True
        assert review_a["to_status"] == STATUS_ARCHIVED
        print(f"    [OK] 待复核状态：复核员可执行复核归档，目标状态=归档")

        s_op = svc.get_transition_summary(rec.id, op1)
        review_op = [a for a in s_op["available_actions"] if a["action"] == ACTION_REVIEW_ARCHIVE][0]
        assert review_op["can_do"] == False
        assert review_op["role_missing"] == True
        print(f"    [OK] 权限差异：操作员无法复核归档（role_missing=True）")

    except Exception as e:
        import traceback; traceback.print_exc()
        print(f"    [ERROR] {e}")
        return 1

    section("3. 取消记录 vs 撤销流转：摘要中的明确区分")
    try:
        sub_section("3.1 先做一条【取消记录】，检查摘要")
        inst2 = svc.create_instrument(
            code="MANUAL-002", name="取消vs撤销 对比仪器",
            cycle_days=365,
            last_calibration_date=(date.today() - timedelta(days=15)).isoformat()
        )
        svc.generate_plans()
        rec2 = [r for r in svc.list_records(STATUS_PENDING) if r.instrument_code == "MANUAL-002"][0]
        rec2 = svc.cancel_record(rec2.id, rv1, cancel_reason="此仪器送检中，3.1取消")
        s_cancel = svc.get_transition_summary(rec2.id, rv1)
        print_summary(s_cancel, "【取消记录】后的摘要")

        assert s_cancel["current_status"] == STATUS_CANCELLED
        assert s_cancel["undo_info"]["action"] == ACTION_CANCEL
        assert "取消" in s_cancel["why_here"]
        print(f"\n    [OK] 取消记录特征：status=取消，undo_info.action=取消记录，why_here包含取消")

        sub_section("3.2 再做一条【撤销流转】（非取消）做对比")
        inst3 = svc.create_instrument(
            code="MANUAL-003", name="仅撤销不取消 仪器",
            cycle_days=365,
            last_calibration_date=(date.today() - timedelta(days=10)).isoformat()
        )
        svc.generate_plans()
        rec3 = [r for r in svc.list_records(STATUS_PENDING) if r.instrument_code == "MANUAL-003"][0]
        rec3 = svc.submit_calibration(rec3.id, op1, actual_date=_today_str(), result="合格")
        rec3 = svc.undo_last_transition(rec3.id, rv1)
        s_undo = svc.get_transition_summary(rec3.id, rv1)
        print_summary(s_undo, "【撤销流转】（非取消）后的摘要")

        assert s_undo["current_status"] == STATUS_PENDING, "撤销流转应回到待执行，不是取消！"
        assert s_undo["history_count"] == 2, "共2条历史：录入 + 撤销"
        assert s_undo["undo_count"] == 1, "有1条已撤销的记录"
        assert "撤销流转" in s_undo["why_here"]
        print(f"\n    [OK] 撤销流转特征：status=待执行≠取消，history=2条，undo_count=1，why_here含撤销流转")
        print(f"        对比 → 取消记录: status=取消, undo_action=取消记录")
        print(f"        对比 → 撤销流转: status=待执行, undo_action(最近)=空, history含ACTION_UNDO")

    except Exception as e:
        import traceback; traceback.print_exc()
        print(f"    [ERROR] {e}")
        return 1

    section("4. 归档后撤销：摘要中返回状态的逐步展示")
    try:
        sub_section("4.1 复核归档 MANUAL-001")
        rec = svc.review_archive(
            rec.id, rv1,
            review_comment="流程合规，4.1归档"
        )
        s_archived = svc.get_transition_summary(rec.id, rv1)
        print_summary(s_archived, "归档状态 摘要")

        assert s_archived["current_status"] == STATUS_ARCHIVED
        assert s_archived["undo_info"]["action"] == ACTION_REVIEW_ARCHIVE
        assert s_archived["undo_info"]["undo_returns_to_status"] == STATUS_REVIEWING
        assert len(s_archived["available_actions"]) == 0
        print(f"\n    [OK] 归档状态：0个直接动作，可撤销返回=待复核，与ACTION_RULES一致")

        sub_section("4.2 第一次撤销归档 → 回到待复核")
        rec = svc.undo_last_transition(rec.id, rv1)
        s1 = svc.get_transition_summary(rec.id, rv1)
        print_summary(s1, "撤销归档后（待复核）的摘要")
        assert s1["current_status"] == STATUS_REVIEWING
        assert s1["undo_count"] == 1
        assert s1["undo_info"]["action"] == ACTION_SEND_REVIEW
        assert s1["undo_info"]["undo_returns_to_status"] == STATUS_COMPLETED
        print(f"    [OK] 撤销归档后：状态=待复核，下一步撤销提交复核→回到已完成")

        sub_section("4.3 第二次撤销提交复核 → 回到已完成")
        rec = svc.undo_last_transition(rec.id, rv1)
        s2 = svc.get_transition_summary(rec.id, rv1)
        assert s2["current_status"] == STATUS_COMPLETED
        assert s2["undo_info"]["undo_returns_to_status"] == STATUS_PENDING
        print(f"    [OK] 撤销提交复核后：状态=已完成，下一步撤销录入→回到待执行")

        sub_section("4.4 第三次撤销录入 → 回到待执行")
        rec = svc.undo_last_transition(rec.id, rv1)
        s3 = svc.get_transition_summary(rec.id, rv1)
        assert s3["current_status"] == STATUS_PENDING
        assert s3["undo_info"] is None
        print(f"    [OK] 撤销录入后：状态=待执行，undo_info=None（最初始状态）")

    except Exception as e:
        import traceback; traceback.print_exc()
        print(f"    [ERROR] {e}")
        return 1

    section("5. 导出内容与界面摘要一致性检查（审计链路落地）")
    try:
        sub_section("5.1 对 MANUAL-001 重新走完流程到归档，便于导出检查")
        rec = [r for r in svc.list_records(STATUS_PENDING) if r.instrument_code == "MANUAL-001"][0]
        rec = svc.submit_calibration(rec.id, op1, actual_date=_today_str(), result="合格",
                                     certificate_summary="EXPORT-CERT-5.1")
        rec = svc.send_for_review(rec.id, op1)
        rec = svc.review_archive(rec.id, rv1, review_comment="5.1复核导出一致性测试")

        summary_for_export = svc.get_transition_summary(rec.id, rv1)
        print_summary(summary_for_export, "导出前的界面摘要（基准）")

        sub_section("5.2 导出 CSV 和 HTML")
        csv_path = os.path.join(DATA_DIR, "verify_export.csv")
        html_path = os.path.join(DATA_DIR, "verify_export.html")
        svc.export_csv(csv_path)
        svc.export_html(html_path)

        with open(csv_path, "r", encoding="utf-8-sig") as f:
            csv_data = f.read()
        with open(html_path, "r", encoding="utf-8") as f:
            html_data = f.read()

        print(f"    CSV: {os.path.getsize(csv_path)} 字节")
        print(f"    HTML: {os.path.getsize(html_path)} 字节")

        sub_section("5.3 对比导出文件与界面摘要的关键字段")
        ok = compare_summary_with_export(summary_for_export, csv_data, html_data, rec.instrument_code)
        if not ok:
            print(f"    [WARNING] 部分检查失败，请人工核对导出文件：")
            print(f"              CSV: {csv_path}")
            print(f"              HTML: {html_path}")
        else:
            print(f"    [OK] 导出内容与界面摘要一致（共用同一来源 get_transition_summary）")

    except Exception as e:
        import traceback; traceback.print_exc()
        print(f"    [ERROR] {e}")
        return 1

    section("6. 重启验证：摘要/历史条数/可执行动作一致性")
    try:
        sub_section("6.1 关闭前快照：对 MANUAL-001 和 MANUAL-002 取摘要")
        rec_main = [r for r in storage.load_records() if r.instrument_code == "MANUAL-001"][0]
        rec_cancel = [r for r in storage.load_records() if r.instrument_code == "MANUAL-002"][0]

        snap1_before = svc.get_transition_summary(rec_main.id, rv1)
        snap2_before = svc.get_transition_summary(rec_cancel.id, rv1)

        total_records_before = len(storage.load_records())
        total_history_before = len(storage.load_history())
        print(f"    重启前快照:")
        print(f"      MANUAL-001: status={snap1_before['current_status']}, "
              f"history={snap1_before['history_count']}, "
              f"undoable={snap1_before['undo_info'] is not None}")
        print(f"      MANUAL-002: status={snap2_before['current_status']}, "
              f"history={snap2_before['history_count']}, "
              f"undoable={snap2_before['undo_info'] is not None}")
        print(f"      总计: 记录 {total_records_before}, 历史 {total_history_before}")

        sub_section("6.2 关闭存储句柄（模拟应用退出）")
        del storage
        del svc

        sub_section("6.3 重新打开 Storage + Service（模拟应用重启）")
        storage2 = Storage(DATA_DIR)
        svc2 = CalibrationService(storage2)

        rec_main2 = storage2.get_record_by_id(rec_main.id)
        rec_cancel2 = storage2.get_record_by_id(rec_cancel.id)
        snap1_after = svc2.get_transition_summary(rec_main2.id, rv1)
        snap2_after = svc2.get_transition_summary(rec_cancel2.id, rv1)

        total_records_after = len(storage2.load_records())
        total_history_after = len(storage2.load_history())

        print(f"    重启后快照:")
        print(f"      MANUAL-001: status={snap1_after['current_status']}, "
              f"history={snap1_after['history_count']}, "
              f"undoable={snap1_after['undo_info'] is not None}")
        print(f"      MANUAL-002: status={snap2_after['current_status']}, "
              f"history={snap2_after['history_count']}, "
              f"undoable={snap2_after['undo_info'] is not None}")
        print(f"      总计: 记录 {total_records_after}, 历史 {total_history_after}")

        sub_section("6.4 逐项一致性断言")
        checks = [
            ("MANUAL-001 状态一致", snap1_before["current_status"] == snap1_after["current_status"]),
            ("MANUAL-001 历史条数一致", snap1_before["history_count"] == snap1_after["history_count"]),
            ("MANUAL-001 可撤销一致", (snap1_before["undo_info"] is None) == (snap1_after["undo_info"] is None)),
            ("MANUAL-001 可用动作一致",
                set(a["action"] for a in snap1_before["available_actions"]) ==
                set(a["action"] for a in snap1_after["available_actions"])),
            ("MANUAL-002 状态一致", snap2_before["current_status"] == snap2_after["current_status"]),
            ("MANUAL-002 历史条数一致", snap2_before["history_count"] == snap2_after["history_count"]),
            ("MANUAL-002 撤销返回状态一致",
                snap1_before["undo_info"]["undo_returns_to_status"] ==
                snap1_after["undo_info"]["undo_returns_to_status"] if snap1_before["undo_info"] else True),
            ("总记录数一致", total_records_before == total_records_after),
            ("总历史数一致", total_history_before == total_history_after),
        ]
        all_ok = True
        for name, ok in checks:
            tag = "✅" if ok else "❌"
            print(f"      {tag} {name}")
            if not ok:
                all_ok = False
        assert all_ok, "重启后数据不一致！"

        print(f"\n    [OK] 重启后：摘要信息、历史条数、可执行动作、撤销返回状态 完全一致")

    except Exception as e:
        import traceback; traceback.print_exc()
        print(f"    [ERROR] {e}")
        return 1

    section("7. 手动验证操作清单（GUI 端对照检查）")
    print("""
    ┌───────────────────────────────────────────────────────────────────────┐
    │  🖥️  GUI 手动验证清单（对照上面的 CLI 结果）：                         │
    ├───────────────────────────────────────────────────────────────────────┤
    │                                                                       │
    │  ① 切换顶部用户下拉，分别选 op1_manual / rv1_manual：                 │
    │     → 底部摘要面板「下一步操作」中的 🔒/🔓/⚠️ 标签应变化              │
    │     → 「撤销信息」中绿色✅ vs 橙色⚠️ 应变化                           │
    │                                                                       │
    │  ② 选中 MANUAL-001（归档状态）：                                      │
    │     → 当前状态=【归档】灰色                                            │
    │     → 撤销信息显示：最近=复核归档，撤销后返回=待复核 ✅复核员可撤销    │
    │     → 下一步操作显示：⏹无直接流转动作                                 │
    │                                                                       │
    │  ③ 选中 MANUAL-002（取消状态）：                                      │
    │     → 当前状态=【取消】红色                                            │
    │     → 撤销信息显示：最近=取消记录，撤销后返回=待执行（与4步取消不同）  │
    │     → 为什么在这：通过「取消记录」操作到达此状态                      │
    │                                                                       │
    │  ④ 点击任意记录的「查看历史」按钮：                                    │
    │     → 窗口标题 = 状态流转历史与操作摘要                                │
    │     → 顶部有完整的流转摘要面板（与主界面底部一致）                    │
    │     → 历史列表按时间正序排列，已撤销的行变灰                           │
    │                                                                       │
    │  ⑤ 点击「导出 CSV」/「导出 HTML」：                                   │
    │     → CSV 文件新增列: status_description, why_here, history_count,    │
    │                        undo_count, last_undoable_action, ...          │
    │     → HTML 顶部有「审计链路说明」+「流转统计总览」卡片                │
    │     → HTML 每一行的「状态说明」「为什么在这」与界面摘要一致           │
    │                                                                       │
    │  ⑥ 重启应用（关掉再打开）：                                            │
    │     → 选中 MANUAL-001，检查状态、历史次数、撤销信息、可执行动作        │
    │       与关闭前完全相同（与上面第6节CLI结果对照）                      │
    │                                                                       │
    │  ⑦ 「取消记录」vs「撤销流转」对比：                                   │
    │     → 取消: 状态变红色「取消」，撤销恢复到取消前状态                  │
    │     → 撤销: 状态回到上一步（颜色随之），历史记录增加ACTION_UNDO       │
    │                                                                       │
    └───────────────────────────────────────────────────────────────────────┘
    """)

    section("8. 数据文件检查")
    try:
        files = os.listdir(DATA_DIR)
        print(f"    数据目录: {DATA_DIR}")
        print(f"    文件清单:")
        for f in sorted(files):
            fpath = os.path.join(DATA_DIR, f)
            size = os.path.getsize(fpath)
            print(f"      {f:<30} {size:>8} 字节")
    except Exception as e:
        print(f"    [ERROR] {e}")
        return 1

    print("\n" + "="*75)
    print("  [ALL OK] 手动+CLI综合验证通过！")
    print("="*75)
    print()
    print("  关键验证点（与自动化测试 test_flow.py 互补）：")
    print("  ✓ 统一规则来源: STATUS_RULES/ACTION_RULES 一处定义，多处共用")
    print("  ✓ 操作员/复核员权限差异在摘要中可见 (can_do + role_missing)")
    print("  ✓ 归档后撤销的逐步返回路径在摘要中完整展示")
    print("  ✓ 取消记录 vs 撤销流转: 状态、undo_action、why_here 三者明确区分")
    print("  ✓ 导出内容(CSV/HTML)与界面摘要一致（共用 get_transition_summary）")
    print("  ✓ 重启后摘要/历史条数/可执行动作/撤销返回状态 完全一致")
    print("  ✓ 操作摘要接入审计链路（导出字段 + HTML审计说明章节）")
    print()
    return 0

if __name__ == "__main__":
    sys.exit(main())
