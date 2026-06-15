import os
import tkinter as tk
from tkinter import ttk, messagebox, filedialog
from datetime import date

from ..models import (
    Instrument, CalibrationRecord, User,
    STATUS_PENDING, STATUS_COMPLETED, STATUS_REVIEWING,
    STATUS_ARCHIVED, STATUS_CANCELLED,
    ROLE_OPERATOR, ROLE_REVIEWER,
    _today_str, parse_date, TransitionLog,
    get_status_info
)
from ..storage import Storage, ValidationError, StorageError
from ..service import CalibrationService
from .dialogs import (
    InstrumentDialog, CalibrationSubmitDialog,
    ReviewDialog, CancelDialog, HistoryDialog
)


class App(tk.Tk):
    def __init__(self, data_dir: str = None):
        super().__init__()
        self.title("仪器校准排程与记录系统")
        self.geometry("1200x750")
        self.minsize(1000, 600)

        if data_dir is None:
            data_dir = os.path.join(os.path.dirname(os.path.dirname(
                os.path.abspath(__file__))), "data")
        self.data_dir = data_dir
        self.storage = Storage(data_dir)
        self.service = CalibrationService(self.storage)
        self.current_user = self.service.get_current_user()

        self._build_style()
        self._build_top_bar()
        self._build_notebook()
        self._build_summary_panel()
        self._build_status_bar()

        self._bind_tree_events()

        self.refresh_all()

    def _build_style(self):
        style = ttk.Style(self)
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass
        style.configure("Treeview", rowheight=26, font=("", 10))
        style.configure("Treeview.Heading", font=("", 10, "bold"))
        style.configure("Status.TLabel", padding=6)
        style.map("Treeview",
                  background=[("selected", "#3498db")],
                  foreground=[("selected", "white")])

    def _build_top_bar(self):
        top = ttk.Frame(self, padding=(10, 8))
        top.pack(fill="x")

        ttk.Label(top, text="仪器校准排程与记录系统",
                  font=("", 14, "bold")).pack(side="left")

        ttk.Separator(top, orient="vertical").pack(side="left", fill="y", padx=12)

        ttk.Label(top, text="当前用户:").pack(side="left")
        self.user_var = tk.StringVar()
        self.user_cb = ttk.Combobox(top, textvariable=self.user_var,
                                    width=18, state="readonly")
        self.user_cb.pack(side="left", padx=5)
        self.user_cb.bind("<<ComboboxSelected>>", self._on_user_change)

        self.role_var = tk.StringVar()
        self.role_lbl = ttk.Label(top, textvariable=self.role_var,
                                   foreground="#2980b9")
        self.role_lbl.pack(side="left", padx=5)

        ttk.Button(top, text="刷新数据", command=self.refresh_all).pack(
            side="right", padx=4)
        ttk.Button(top, text="导出 CSV", command=self.export_csv).pack(
            side="right", padx=4)
        ttk.Button(top, text="导出 HTML", command=self.export_html).pack(
            side="right", padx=4)

    def _build_notebook(self):
        self.nb = ttk.Notebook(self)
        self.nb.pack(fill="both", expand=True, padx=10, pady=5)

        self._build_instruments_tab()
        self._build_pending_tab()
        self._build_completed_tab()
        self._build_reviewing_tab()
        self._build_archived_tab()
        self._build_cancelled_tab()

    def _build_status_bar(self):
        self.status_var = tk.StringVar(value="就绪")
        bar = ttk.Frame(self)
        bar.pack(fill="x", side="bottom")
        ttk.Label(bar, textvariable=self.status_var, style="Status.TLabel").pack(
            side="left", padx=10)

    # ---- Transition Summary Panel ----
    def _build_summary_panel(self):
        outer = ttk.LabelFrame(self, text=" 操作摘要 / 流转说明 (选中记录后查看详情) ", padding=(8, 6))
        outer.pack(fill="x", padx=10, pady=(0, 5))

        self.summary_container = ttk.Frame(outer)
        self.summary_container.pack(fill="x")

        left = ttk.Frame(self.summary_container)
        left.pack(side="left", fill="both", expand=True)

        row1 = ttk.Frame(left)
        row1.pack(fill="x", pady=2)
        ttk.Label(row1, text="当前状态:", font=("", 10, "bold")).pack(side="left")
        self.summary_status_lbl = ttk.Label(row1, text="(未选中记录)", foreground="#7f8c8d")
        self.summary_status_lbl.pack(side="left", padx=6)

        row2 = ttk.Frame(left)
        row2.pack(fill="x", pady=2)
        ttk.Label(row2, text="状态说明:", font=("", 9)).pack(side="left", anchor="n")
        self.summary_desc_lbl = ttk.Label(row2, text="请在上方列表中选择一条校准记录，查看当前状态的含义、下一步可执行操作、最近一次流转能否撤销等信息。",
                                           wraplength=700, justify="left", foreground="#34495e")
        self.summary_desc_lbl.pack(side="left", padx=6, fill="x", expand=True)

        row3 = ttk.Frame(left)
        row3.pack(fill="x", pady=2)
        ttk.Label(row3, text="为什么在这:", font=("", 9)).pack(side="left", anchor="n")
        self.summary_why_lbl = ttk.Label(row3, text="—", wraplength=700, justify="left", foreground="#5d6d7e")
        self.summary_why_lbl.pack(side="left", padx=6, fill="x", expand=True)

        right = ttk.Frame(self.summary_container)
        right.pack(side="right", fill="both", expand=True)

        row_r1 = ttk.Frame(right)
        row_r1.pack(fill="x", pady=2)
        ttk.Label(row_r1, text="历史/撤销:", font=("", 9, "bold")).pack(side="left")
        self.summary_history_lbl = ttk.Label(row_r1, text="共 0 条流转记录，0 条已撤销", foreground="#5d6d7e")
        self.summary_history_lbl.pack(side="left", padx=6)

        row_r2 = ttk.Frame(right)
        row_r2.pack(fill="x", pady=2)
        ttk.Label(row_r2, text="撤销信息:", font=("", 9)).pack(side="left", anchor="n")
        self.summary_undo_lbl = ttk.Label(row_r2, text="无可撤销的流转操作", wraplength=500, justify="left", foreground="#7f8c8d")
        self.summary_undo_lbl.pack(side="left", padx=6, fill="x", expand=True)

        actions_frame = ttk.LabelFrame(self, text=" 下一步可执行操作 ", padding=(8, 4))
        actions_frame.pack(fill="x", padx=10, pady=(0, 5))
        self.summary_actions_lbl = ttk.Label(actions_frame, text="(选中记录后显示当前角色可执行的操作及说明)",
                                              wraplength=1100, justify="left", foreground="#2c3e50")
        self.summary_actions_lbl.pack(fill="x", padx=2, pady=2)

    def _bind_tree_events(self):
        for tree in [self.pending_tree, self.completed_tree, self.reviewing_tree,
                     self.archived_tree, self.cancelled_tree]:
            tree.bind("<<TreeviewSelect>>", self._on_tree_select)
        self.nb.bind("<<NotebookTabChanged>>", self._on_tab_change)

    def _on_tab_change(self, _ev=None):
        tree = self._get_current_tree()
        if tree is not None:
            rid = self._selected_id(tree)
            if rid:
                self._refresh_summary(rid)
            else:
                self._clear_summary()
        else:
            self._clear_summary()

    def _on_tree_select(self, _ev=None):
        tree = self._get_current_tree()
        if tree is None:
            self._clear_summary()
            return
        rid = self._selected_id(tree)
        if rid:
            self._refresh_summary(rid)
        else:
            self._clear_summary()

    def _clear_summary(self):
        self.summary_status_lbl.configure(text="(未选中记录)", foreground="#7f8c8d")
        self.summary_desc_lbl.configure(text="请在上方列表中选择一条校准记录，查看当前状态的含义、下一步可执行操作、最近一次流转能否撤销等信息。")
        self.summary_why_lbl.configure(text="—")
        self.summary_history_lbl.configure(text="共 0 条流转记录，0 条已撤销")
        self.summary_undo_lbl.configure(text="无可撤销的流转操作", foreground="#7f8c8d")
        self.summary_actions_lbl.configure(text="(选中记录后显示当前角色可执行的操作及说明)")

    def _refresh_summary(self, record_id: str):
        try:
            summary = self.service.get_transition_summary(record_id, self.current_user)
        except (StorageError, ValidationError) as e:
            self._clear_summary()
            self.summary_desc_lbl.configure(text=f"获取摘要失败: {e}", foreground="#c0392b")
            return

        status_info = summary["current_status_info"]
        status_color = status_info.get("color", "#2c3e50")
        self.summary_status_lbl.configure(
            text=f"【{summary['current_status']}】",
            foreground=status_color,
            font=("", 11, "bold")
        )
        self.summary_desc_lbl.configure(text=status_info.get("description", ""))
        self.summary_why_lbl.configure(text=summary["why_here"])
        self.summary_history_lbl.configure(
            text=f"共 {summary['history_count']} 条流转记录，{summary['undo_count']} 条已撤销",
            foreground="#5d6d7e"
        )

        undo_info = summary["undo_info"]
        if undo_info:
            undo_parts = [
                f"最近一次操作:「{undo_info['action']}」",
                f"操作人: {undo_info['by_user']}",
                f"时间: {undo_info['created_at']}",
                f"撤销后返回:「{undo_info['undo_returns_to_status']}」",
                f"({undo_info['undo_returns_to_description']})",
            ]
            if undo_info["reason"]:
                undo_parts.append(f"原操作原因: {undo_info['reason']}")
            if undo_info["can_do"]:
                undo_parts.append("✅ 当前角色【复核员】可执行撤销")
                undo_color = "#27ae60"
            elif undo_info["undo_role_missing"]:
                undo_parts.append(f"⚠️ 需【{undo_info['required_role']}】权限，当前角色【{summary['user_role']}】无法撤销")
                undo_color = "#e67e22"
            else:
                undo_parts.append(f"⚠️ 需【{undo_info['required_role']}】权限")
                undo_color = "#e67e22"
            self.summary_undo_lbl.configure(text=" | ".join(undo_parts), foreground=undo_color)
        else:
            self.summary_undo_lbl.configure(text="无可撤销的流转操作（此状态为初始状态或已撤销到最早状态）", foreground="#7f8c8d")

        actions = summary["available_actions"]
        if not actions:
            actions_text = "⏹ 当前状态无直接可执行的流转操作。可通过「撤销流转」回退到上一步（如有）。"
        else:
            action_lines = []
            for a in actions:
                role_note = ""
                if a["role_missing"]:
                    role_note = f" ⚠️需【{a['required_role']}】权限"
                    action_color = "#e67e22"
                elif a["required_role"]:
                    role_note = f" 🔒需【{a['required_role']}】权限"
                    action_color = "#27ae60"
                else:
                    role_note = " 🔓所有角色可操作"
                    action_color = "#2980b9"
                line = (
                    f"• 【{a['button_label']}】{role_note}\n"
                    f"   说明: {a['description']}\n"
                    f"   执行后状态: 「{a['to_status']}」— {a['to_status_description']}"
                )
                if a["fields_required"]:
                    line += f"\n   必填: {', '.join(a['fields_required'])}"
                if a["fields_optional"]:
                    line += f"\n   选填: {', '.join(a['fields_optional'])}"
                action_lines.append(line)
            actions_text = "\n\n".join(action_lines)
        self.summary_actions_lbl.configure(text=actions_text)

    # ---- Instruments tab ----
    def _build_instruments_tab(self):
        frm = ttk.Frame(self.nb, padding=8)
        self.nb.add(frm, text=" 仪器台账 ")

        toolbar = ttk.Frame(frm)
        toolbar.pack(fill="x", pady=(0, 6))
        ttk.Button(toolbar, text="新增仪器", command=self.add_instrument).pack(
            side="left", padx=2)
        ttk.Button(toolbar, text="编辑选中", command=self.edit_instrument).pack(
            side="left", padx=2)
        ttk.Button(toolbar, text="生成校准计划", command=self.generate_plans).pack(
            side="left", padx=12)
        ttk.Label(toolbar, text="搜索:").pack(side="left", padx=(10, 4))
        self.inst_search = tk.StringVar()
        e = ttk.Entry(toolbar, textvariable=self.inst_search, width=20)
        e.pack(side="left")
        e.bind("<KeyRelease>", lambda ev: self.refresh_instruments())

        cols = ("code", "name", "model", "manufacturer", "location",
                "cycle_days", "last_calibration_date", "owner", "remark")
        self.inst_tree = self._create_tree(frm, cols, {
            "code": ("编号", 100), "name": ("名称", 140),
            "model": ("型号", 120), "manufacturer": ("厂家", 120),
            "location": ("地点", 100), "cycle_days": ("周期(天)", 80),
            "last_calibration_date": ("上次校准", 100),
            "owner": ("责任人", 90), "remark": ("备注", 180),
        })
        self.inst_tree.bind("<Double-1>", lambda ev: self.edit_instrument())

    # ---- Pending tab ----
    def _build_pending_tab(self):
        frm = ttk.Frame(self.nb, padding=8)
        self.nb.add(frm, text=f" {STATUS_PENDING} ")

        toolbar = ttk.Frame(frm)
        toolbar.pack(fill="x", pady=(0, 6))
        ttk.Label(toolbar, text="此列表中的记录等待执行校准").pack(side="left")
        ttk.Button(toolbar, text="查看历史", command=self.view_history).pack(
            side="right", padx=2)
        ttk.Button(toolbar, text="撤销上一次流转", command=self.undo_last_transition).pack(
            side="right", padx=2)
        ttk.Button(toolbar, text="取消记录", command=self.cancel_record).pack(
            side="right", padx=2)
        ttk.Button(toolbar, text="录入校准结果", command=self.submit_calibration).pack(
            side="right", padx=2)

        cols = ("instrument_code", "instrument_name", "planned_date",
                "is_overdue", "operator", "created_at")
        self.pending_tree = self._create_tree(frm, cols, {
            "instrument_code": ("仪器编号", 100),
            "instrument_name": ("仪器名称", 160),
            "planned_date": ("计划日期", 100),
            "is_overdue": ("是否超期", 80),
            "operator": ("责任人", 100),
            "created_at": ("创建日期", 100),
        })
        self.pending_tree.bind("<Double-1>", lambda ev: self.submit_calibration())

    # ---- Completed tab ----
    def _build_completed_tab(self):
        frm = ttk.Frame(self.nb, padding=8)
        self.nb.add(frm, text=f" {STATUS_COMPLETED} ")

        toolbar = ttk.Frame(frm)
        toolbar.pack(fill="x", pady=(0, 6))
        ttk.Label(toolbar, text="校准已完成，等待提交复核").pack(side="left")
        ttk.Button(toolbar, text="查看历史", command=self.view_history).pack(
            side="right", padx=2)
        ttk.Button(toolbar, text="撤销上一次流转", command=self.undo_last_transition).pack(
            side="right", padx=2)
        ttk.Button(toolbar, text="取消记录", command=self.cancel_record).pack(
            side="right", padx=2)
        ttk.Button(toolbar, text="提交复核", command=self.send_for_review).pack(
            side="right", padx=2)

        cols = ("instrument_code", "instrument_name", "planned_date",
                "actual_date", "result", "is_overdue", "operator", "certificate_summary")
        self.completed_tree = self._create_tree(frm, cols, {
            "instrument_code": ("仪器编号", 100),
            "instrument_name": ("仪器名称", 160),
            "planned_date": ("计划日期", 100),
            "actual_date": ("实际日期", 100),
            "result": ("结果", 80),
            "is_overdue": ("超期", 60),
            "operator": ("操作员", 90),
            "certificate_summary": ("证书摘要", 300),
        })
        self.completed_tree.bind("<Double-1>", lambda ev: self.send_for_review())

    # ---- Reviewing tab ----
    def _build_reviewing_tab(self):
        frm = ttk.Frame(self.nb, padding=8)
        self.nb.add(frm, text=f" {STATUS_REVIEWING} ")

        toolbar = ttk.Frame(frm)
        toolbar.pack(fill="x", pady=(0, 6))
        ttk.Label(toolbar, text="已提交，等待复核员归档").pack(side="left")
        ttk.Button(toolbar, text="查看历史", command=self.view_history).pack(
            side="right", padx=2)
        ttk.Button(toolbar, text="撤销上一次流转", command=self.undo_last_transition).pack(
            side="right", padx=2)
        ttk.Button(toolbar, text="取消记录", command=self.cancel_record).pack(
            side="right", padx=2)
        ttk.Button(toolbar, text="复核并归档", command=self.review_archive).pack(
            side="right", padx=2)

        cols = ("instrument_code", "instrument_name", "actual_date",
                "result", "operator", "certificate_summary")
        self.reviewing_tree = self._create_tree(frm, cols, {
            "instrument_code": ("仪器编号", 100),
            "instrument_name": ("仪器名称", 160),
            "actual_date": ("校准日期", 100),
            "result": ("结果", 80),
            "operator": ("操作员", 90),
            "certificate_summary": ("证书摘要", 380),
        })
        self.reviewing_tree.bind("<Double-1>", lambda ev: self.review_archive())

    # ---- Archived tab ----
    def _build_archived_tab(self):
        frm = ttk.Frame(self.nb, padding=8)
        self.nb.add(frm, text=f" {STATUS_ARCHIVED} ")

        toolbar = ttk.Frame(frm)
        toolbar.pack(fill="x", pady=(0, 6))
        ttk.Label(toolbar, text="已完成全部流程的历史记录（可撤销回到待复核）").pack(side="left")
        ttk.Button(toolbar, text="查看历史", command=self.view_history).pack(
            side="right", padx=2)
        ttk.Button(toolbar, text="撤销上一次流转", command=self.undo_last_transition).pack(
            side="right", padx=2)

        cols = ("instrument_code", "instrument_name", "actual_date",
                "result", "operator", "reviewer", "review_comment",
                "archived_at")
        self.archived_tree = self._create_tree(frm, cols, {
            "instrument_code": ("仪器编号", 90),
            "instrument_name": ("仪器名称", 140),
            "actual_date": ("校准日期", 90),
            "result": ("结果", 70),
            "operator": ("操作员", 80),
            "reviewer": ("复核人", 80),
            "review_comment": ("复核意见", 260),
            "archived_at": ("归档时间", 100),
        })

    # ---- Cancelled tab ----
    def _build_cancelled_tab(self):
        frm = ttk.Frame(self.nb, padding=8)
        self.nb.add(frm, text=f" {STATUS_CANCELLED}记录 ")

        toolbar = ttk.Frame(frm)
        toolbar.pack(fill="x", pady=(0, 6))
        ttk.Label(toolbar, text="已取消的校准记录（可撤销恢复）").pack(side="left")
        ttk.Button(toolbar, text="查看历史", command=self.view_history).pack(
            side="right", padx=2)
        ttk.Button(toolbar, text="撤销上一次流转（恢复）", command=self.undo_last_transition).pack(
            side="right", padx=2)

        cols = ("instrument_code", "instrument_name", "planned_date",
                "status", "cancelled_by", "cancel_reason", "updated_at")
        self.cancelled_tree = self._create_tree(frm, cols, {
            "instrument_code": ("仪器编号", 100),
            "instrument_name": ("仪器名称", 160),
            "planned_date": ("计划日期", 100),
            "status": ("取消前状态", 80),
            "cancelled_by": ("取消人", 90),
            "cancel_reason": ("取消原因", 300),
            "updated_at": ("取消时间", 100),
        })

    # ---- Tree helpers ----
    def _create_tree(self, parent, columns, col_map):
        container = ttk.Frame(parent)
        container.pack(fill="both", expand=True)
        tree = ttk.Treeview(container, columns=columns, show="headings", selectmode="browse")
        for col, (title, width) in col_map.items():
            tree.heading(col, text=title)
            tree.column(col, width=width, anchor="w")
        vsb = ttk.Scrollbar(container, orient="vertical", command=tree.yview)
        tree.configure(yscrollcommand=vsb.set)
        tree.pack(side="left", fill="both", expand=True)
        vsb.pack(side="right", fill="y")
        return tree

    def _fill_tree(self, tree, records, columns):
        tree.delete(*tree.get_children())
        for r in records:
            values = []
            for c in columns:
                v = getattr(r, c, "")
                if v is None:
                    v = ""
                if isinstance(v, bool):
                    v = "是" if v else "否"
                values.append(str(v))
            tree.insert("", "end", iid=r.id, values=values)

    def _selected_id(self, tree) -> str:
        sel = tree.selection()
        return sel[0] if sel else ""

    # ---- Users ----
    def _refresh_user_combobox(self):
        users = self.service.get_all_users()
        self.user_cb["values"] = [u.username for u in users]
        self.user_var.set(self.current_user.username)
        self.role_var.set(f"[角色: {self.current_user.role}]")

    # ---- Status ----
    def set_status(self, msg: str):
        self.status_var.set(msg)

    # ---- Instruments ----
    def refresh_instruments(self):
        q = self.inst_search.get().strip().lower()
        instruments = self.service.list_instruments()
        if q:
            instruments = [i for i in instruments
                           if q in i.code.lower() or q in i.name.lower()]
        self._fill_tree(self.inst_tree, instruments,
                        ("code", "name", "model", "manufacturer", "location",
                         "cycle_days", "last_calibration_date", "owner", "remark"))

    def add_instrument(self):
        dlg = InstrumentDialog(self)
        self.wait_window(dlg)
        if not dlg.result:
            return
        try:
            self.service.create_instrument(**dlg.result)
            self.set_status("新增仪器成功")
            self.refresh_instruments()
            messagebox.showinfo("成功", "仪器已添加到台账", parent=self)
        except ValidationError as e:
            messagebox.showerror("校验失败", str(e), parent=self)
            self.set_status(f"新增仪器失败: {e}")
        except StorageError as e:
            messagebox.showerror("存储错误", str(e), parent=self)

    def edit_instrument(self):
        iid = self._selected_id(self.inst_tree)
        if not iid:
            messagebox.showwarning("提示", "请先选择一台仪器", parent=self)
            return
        inst = self.storage.get_instrument_by_id(iid)
        if not inst:
            return
        dlg = InstrumentDialog(self, inst)
        self.wait_window(dlg)
        if not dlg.result:
            return
        try:
            self.service.update_instrument(inst.id, **dlg.result)
            self.set_status("仪器信息已更新")
            self.refresh_instruments()
            messagebox.showinfo("成功", "仪器信息已更新", parent=self)
        except ValidationError as e:
            messagebox.showerror("校验失败", str(e), parent=self)
        except StorageError as e:
            messagebox.showerror("存储错误", str(e), parent=self)

    # ---- Plans ----
    def generate_plans(self):
        try:
            created = self.service.generate_plans()
            self.refresh_records()
            if created:
                self.set_status(f"已生成 {len(created)} 条校准计划")
                messagebox.showinfo("计划生成",
                                    f"成功生成 {len(created)} 条校准计划",
                                    parent=self)
            else:
                self.set_status("没有需要生成计划的仪器")
                messagebox.showinfo("计划生成",
                                    "所有仪器已有未完成计划，无需生成新计划",
                                    parent=self)
        except ValidationError as e:
            messagebox.showerror("错误", str(e), parent=self)

    # ---- Records ----
    def refresh_records(self):
        pending = self.service.list_records(STATUS_PENDING)
        self._fill_tree(self.pending_tree, pending,
                        ("instrument_code", "instrument_name", "planned_date",
                         "is_overdue", "operator", "created_at"))

        completed = self.service.list_records(STATUS_COMPLETED)
        self._fill_tree(self.completed_tree, completed,
                        ("instrument_code", "instrument_name", "planned_date",
                         "actual_date", "result", "is_overdue",
                         "operator", "certificate_summary"))

        reviewing = self.service.list_records(STATUS_REVIEWING)
        self._fill_tree(self.reviewing_tree, reviewing,
                        ("instrument_code", "instrument_name", "actual_date",
                         "result", "operator", "certificate_summary"))

        archived = self.service.list_records(STATUS_ARCHIVED)
        self._fill_tree(self.archived_tree, archived,
                        ("instrument_code", "instrument_name", "actual_date",
                         "result", "operator", "reviewer",
                         "review_comment", "archived_at"))

        cancelled = self.service.list_cancelled_records()
        self._fill_tree(self.cancelled_tree, cancelled,
                        ("instrument_code", "instrument_name", "planned_date",
                         "status", "cancelled_by", "cancel_reason", "updated_at"))

        self._on_tab_change()

    def refresh_all(self):
        self._refresh_user_combobox()
        self.refresh_instruments()
        self.refresh_records()
        self.set_status("数据已刷新")

    def _on_user_change(self, _ev=None):
        username = self.user_var.get()
        try:
            self.current_user = self.service.set_current_user(username)
            self.role_var.set(f"[角色: {self.current_user.role}]")
            self.set_status(f"已切换为用户: {username} ({self.current_user.role})")
            self._on_tab_change()
        except ValidationError as e:
            messagebox.showerror("错误", str(e), parent=self)

    # ---- State transitions ----
    def submit_calibration(self):
        rid = self._selected_id(self.pending_tree)
        if not rid:
            messagebox.showwarning("提示", f"请先在「{STATUS_PENDING}」列表中选择一条记录", parent=self)
            return
        rec = self.storage.get_record_by_id(rid)
        if not rec:
            return
        dlg = CalibrationSubmitDialog(self, rec)
        self.wait_window(dlg)
        if not dlg.result:
            return
        try:
            self.service.submit_calibration(rec.id, self.current_user, **dlg.result)
            self.refresh_records()
            self.refresh_instruments()
            self.set_status("校准结果已录入")
            messagebox.showinfo("成功", "校准结果已录入，状态更新为「已完成」", parent=self)
        except ValidationError as e:
            messagebox.showerror("校验失败", str(e), parent=self)
            self.set_status(f"录入失败: {e}")
        except StorageError as e:
            messagebox.showerror("错误", str(e), parent=self)

    def send_for_review(self):
        rid = self._selected_id(self.completed_tree)
        if not rid:
            messagebox.showwarning("提示", f"请先在「{STATUS_COMPLETED}」列表中选择一条记录", parent=self)
            return
        try:
            self.service.send_for_review(rid, self.current_user)
            self.refresh_records()
            self.set_status("已提交复核")
            messagebox.showinfo("成功", "记录已提交复核", parent=self)
        except ValidationError as e:
            messagebox.showerror("校验失败", str(e), parent=self)
        except StorageError as e:
            messagebox.showerror("错误", str(e), parent=self)

    def review_archive(self):
        rid = self._selected_id(self.reviewing_tree)
        if not rid:
            messagebox.showwarning("提示", f"请先在「{STATUS_REVIEWING}」列表中选择一条记录", parent=self)
            return
        rec = self.storage.get_record_by_id(rid)
        if not rec:
            return
        dlg = ReviewDialog(self, rec)
        self.wait_window(dlg)
        if not dlg.result:
            return
        try:
            self.service.review_archive(rec.id, self.current_user, **dlg.result)
            self.refresh_records()
            self.set_status("已复核归档")
            messagebox.showinfo("成功", "记录已复核归档", parent=self)
        except ValidationError as e:
            messagebox.showerror("校验失败", str(e), parent=self)
            self.set_status(f"复核失败: {e}")
        except StorageError as e:
            messagebox.showerror("错误", str(e), parent=self)

    def _get_current_tree(self):
        selected_tab = self.nb.index(self.nb.select())
        trees = [
            None,
            self.pending_tree,
            self.completed_tree,
            self.reviewing_tree,
            self.archived_tree,
            self.cancelled_tree,
        ]
        if 1 <= selected_tab < len(trees):
            return trees[selected_tab]
        return None

    def cancel_record(self):
        tree = self._get_current_tree()
        if tree is None:
            messagebox.showwarning("提示", "请在待执行/已完成/待复核标签页中选择记录", parent=self)
            return
        rid = self._selected_id(tree)
        if not rid:
            messagebox.showwarning("提示", "请先选择一条校准记录", parent=self)
            return
        rec = self.storage.get_record_by_id(rid)
        if not rec:
            return
        dlg = CancelDialog(self, rec)
        self.wait_window(dlg)
        if not dlg.result:
            return
        try:
            self.service.cancel_record(rec.id, self.current_user, **dlg.result)
            self.refresh_records()
            self.refresh_instruments()
            self.set_status(f"记录已取消，原因: {dlg.result['cancel_reason']}")
            messagebox.showinfo("成功",
                "记录已取消，可在「取消记录」标签页查看并支持撤销恢复",
                parent=self)
        except ValidationError as e:
            messagebox.showerror("校验失败", str(e), parent=self)
            self.set_status(f"取消失败: {e}")
        except StorageError as e:
            messagebox.showerror("错误", str(e), parent=self)

    def view_history(self):
        tree = self._get_current_tree()
        if tree is None:
            messagebox.showwarning("提示", "请先选择一条记录", parent=self)
            return
        rid = self._selected_id(tree)
        if not rid:
            messagebox.showwarning("提示", "请先选择一条记录", parent=self)
            return
        rec = self.storage.get_record_by_id(rid)
        if not rec:
            return
        history = self.service.list_history(rec.id)
        try:
            summary = self.service.get_transition_summary(rec.id, self.current_user)
        except (StorageError, ValidationError):
            summary = None
        dlg = HistoryDialog(self, rec, history, summary)
        self.wait_window(dlg)

    def undo_last_transition(self):
        tree = self._get_current_tree()
        if tree is None:
            messagebox.showwarning("提示", "请在记录标签页中选择一条记录", parent=self)
            return
        rid = self._selected_id(tree)
        if not rid:
            messagebox.showwarning("提示", "请先选择一条记录", parent=self)
            return
        rec = self.storage.get_record_by_id(rid)
        if not rec:
            return
        last = self.service.get_undoable_transition(rid)
        if not last:
            messagebox.showinfo("提示", "该记录没有可撤销的流转操作", parent=self)
            return
        msg = (f"确定撤销上一次流转？\n\n"
               f"操作: {last.action}\n"
               f"原状态: {last.from_status}\n"
               f"当前状态: {last.to_status}\n"
               f"操作人: {last.by_user}\n"
               f"时间: {last.created_at}")
        if not messagebox.askyesno("确认撤销流转", msg, parent=self):
            return
        try:
            rec = self.service.undo_last_transition(rid, self.current_user)
            self.refresh_records()
            self.refresh_instruments()
            self.set_status(f"已撤销上一次流转，记录恢复为: {rec.status}")
            messagebox.showinfo("成功",
                f"已撤销上一次流转，记录恢复为「{rec.status}」状态",
                parent=self)
        except ValidationError as e:
            messagebox.showerror("校验失败", str(e), parent=self)
            self.set_status(f"撤销失败: {e}")
        except StorageError as e:
            messagebox.showerror("错误", str(e), parent=self)

    # ---- Export ----
    def export_csv(self):
        path = filedialog.asksaveasfilename(
            parent=self, title="导出 CSV", defaultextension=".csv",
            filetypes=[("CSV 文件", "*.csv"), ("所有文件", "*.*")],
            initialfile=f"calibration_records_{_today_str()}.csv")
        if not path:
            return
        try:
            n = self.service.export_csv(path)
            self.set_status(f"已导出 {n} 条记录到 CSV")
            messagebox.showinfo("导出成功", f"已导出 {n} 条记录到:\n{path}", parent=self)
        except Exception as e:
            messagebox.showerror("导出失败", str(e), parent=self)

    def export_html(self):
        path = filedialog.asksaveasfilename(
            parent=self, title="导出 HTML", defaultextension=".html",
            filetypes=[("HTML 文件", "*.html"), ("所有文件", "*.*")],
            initialfile=f"calibration_records_{_today_str()}.html")
        if not path:
            return
        try:
            n = self.service.export_html(path)
            self.set_status(f"已导出 {n} 条记录到 HTML")
            messagebox.showinfo("导出成功", f"已导出 {n} 条记录到:\n{path}", parent=self)
        except Exception as e:
            messagebox.showerror("导出失败", str(e), parent=self)
