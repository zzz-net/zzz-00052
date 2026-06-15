import tkinter as tk
from tkinter import ttk, messagebox
from datetime import date, timedelta
from typing import List

from ..models import (
    Instrument, CalibrationRecord, User, TransitionLog,
    STATUS_PENDING, STATUS_COMPLETED, STATUS_REVIEWING,
    STATUS_ARCHIVED, STATUS_CANCELLED, ROLE_REVIEWER,
    parse_date, is_valid_date, _today_str, get_status_info,
    is_terminal_status, get_status_summary_label
)
from typing import Dict, Any


def _grid_label_entry(parent, label: str, row: int, value: str = "",
                      width: int = 30, readonly: bool = False) -> ttk.Entry:
    ttk.Label(parent, text=label).grid(row=row, column=0, sticky="e", padx=5, pady=3)
    var = tk.StringVar(value=value)
    entry = ttk.Entry(parent, textvariable=var, width=width,
                      state="readonly" if readonly else "normal")
    entry.grid(row=row, column=1, sticky="w", padx=5, pady=3)
    entry._var = var
    return entry


def _grid_label_combobox(parent, label: str, row: int, values, value: str = "",
                         width: int = 28, readonly: bool = True) -> ttk.Combobox:
    ttk.Label(parent, text=label).grid(row=row, column=0, sticky="e", padx=5, pady=3)
    var = tk.StringVar(value=value)
    cb = ttk.Combobox(parent, textvariable=var, values=values, width=width,
                      state="readonly" if readonly else "normal")
    cb.grid(row=row, column=1, sticky="w", padx=5, pady=3)
    cb._var = var
    return cb


def _grid_label_text(parent, label: str, row: int, value: str = "",
                     height: int = 4, width: int = 40) -> tk.Text:
    ttk.Label(parent, text=label).grid(row=row, column=0, sticky="ne", padx=5, pady=3)
    text = tk.Text(parent, height=height, width=width)
    text.grid(row=row, column=1, sticky="w", padx=5, pady=3)
    text.insert("1.0", value)
    return text


def _get_text_content(text: tk.Text) -> str:
    return text.get("1.0", "end-1c").strip()


class InstrumentDialog(tk.Toplevel):
    def __init__(self, master, instrument: Instrument = None):
        super().__init__(master)
        self.instrument = instrument
        self.result = None
        self.title("编辑仪器" if instrument else "新增仪器")
        self.resizable(False, False)
        self.transient(master)
        self.grab_set()

        frm = ttk.Frame(self, padding=15)
        frm.pack(fill="both", expand=True)

        default_cycle = instrument.cycle_days if instrument else 365
        default_last = instrument.last_calibration_date if instrument and instrument.last_calibration_date else ""

        self.e_code = _grid_label_entry(frm, "仪器编号 *", 0,
                                        instrument.code if instrument else "")
        self.e_name = _grid_label_entry(frm, "仪器名称 *", 1,
                                        instrument.name if instrument else "")
        self.e_model = _grid_label_entry(frm, "规格型号", 2,
                                         instrument.model if instrument else "")
        self.e_mfr = _grid_label_entry(frm, "生产厂家", 3,
                                       instrument.manufacturer if instrument else "")
        self.e_loc = _grid_label_entry(frm, "放置地点", 4,
                                       instrument.location if instrument else "")
        self.e_cycle = _grid_label_entry(frm, "校准周期(天) *", 5, str(default_cycle))
        self.e_last = _grid_label_entry(frm, "上次校准日期\n(YYYY-MM-DD)", 6, default_last)
        self.e_owner = _grid_label_entry(frm, "责任人", 7,
                                         instrument.owner if instrument else "")
        self.t_remark = _grid_label_text(frm, "备注", 8,
                                         instrument.remark if instrument else "", height=3)

        btns = ttk.Frame(frm)
        btns.grid(row=9, column=0, columnspan=2, pady=10)
        ttk.Button(btns, text="确定", command=self._ok).pack(side="left", padx=8)
        ttk.Button(btns, text="取消", command=self.destroy).pack(side="left", padx=8)

    def _ok(self):
        try:
            cycle = int(self.e_cycle._var.get().strip())
        except ValueError:
            messagebox.showerror("错误", "校准周期必须是整数", parent=self)
            return
        self.result = {
            "code": self.e_code._var.get().strip(),
            "name": self.e_name._var.get().strip(),
            "model": self.e_model._var.get().strip(),
            "manufacturer": self.e_mfr._var.get().strip(),
            "location": self.e_loc._var.get().strip(),
            "cycle_days": cycle,
            "last_calibration_date": self.e_last._var.get().strip(),
            "owner": self.e_owner._var.get().strip(),
            "remark": _get_text_content(self.t_remark),
        }
        self.destroy()


class CalibrationSubmitDialog(tk.Toplevel):
    def __init__(self, master, record: CalibrationRecord):
        super().__init__(master)
        self.record = record
        self.result = None
        self.title("录入校准结果")
        self.resizable(False, False)
        self.transient(master)
        self.grab_set()

        frm = ttk.Frame(self, padding=15)
        frm.pack(fill="both", expand=True)

        ttk.Label(frm, text="仪器编号:").grid(row=0, column=0, sticky="e", padx=5, pady=3)
        ttk.Label(frm, text=record.instrument_code, font=("", 10, "bold")).grid(
            row=0, column=1, sticky="w", padx=5, pady=3)
        ttk.Label(frm, text="仪器名称:").grid(row=1, column=0, sticky="e", padx=5, pady=3)
        ttk.Label(frm, text=record.instrument_name, font=("", 10, "bold")).grid(
            row=1, column=1, sticky="w", padx=5, pady=3)
        ttk.Label(frm, text="计划日期:").grid(row=2, column=0, sticky="e", padx=5, pady=3)
        ttk.Label(frm, text=record.planned_date).grid(row=2, column=1, sticky="w", padx=5, pady=3)

        self.e_actual = _grid_label_entry(frm, "实际校准日期 *\n(YYYY-MM-DD)", 3, _today_str())
        self.cb_result = _grid_label_combobox(
            frm, "校准结果 *", 4,
            ["合格", "不合格", "限制使用", "待维修"],
            "合格", readonly=False)
        self.t_cert = _grid_label_text(frm, "证书摘要", 5, "", height=3)
        self.t_overdue = _grid_label_text(frm, "超期原因\n(超期时必填)", 6, "", height=3)

        btns = ttk.Frame(frm)
        btns.grid(row=7, column=0, columnspan=2, pady=10)
        ttk.Button(btns, text="提交", command=self._ok).pack(side="left", padx=8)
        ttk.Button(btns, text="取消", command=self.destroy).pack(side="left", padx=8)

    def _ok(self):
        self.result = {
            "actual_date": self.e_actual._var.get().strip(),
            "result": self.cb_result._var.get().strip(),
            "certificate_summary": _get_text_content(self.t_cert),
            "overdue_reason": _get_text_content(self.t_overdue),
        }
        self.destroy()


class ReviewDialog(tk.Toplevel):
    def __init__(self, master, record: CalibrationRecord):
        super().__init__(master)
        self.record = record
        self.result = None
        self.title("复核归档")
        self.resizable(False, False)
        self.transient(master)
        self.grab_set()

        frm = ttk.Frame(self, padding=15)
        frm.pack(fill="both", expand=True)

        ttk.Label(frm, text="仪器编号:").grid(row=0, column=0, sticky="e", padx=5, pady=3)
        ttk.Label(frm, text=record.instrument_code, font=("", 10, "bold")).grid(
            row=0, column=1, sticky="w", padx=5, pady=3)
        ttk.Label(frm, text="仪器名称:").grid(row=1, column=0, sticky="e", padx=5, pady=3)
        ttk.Label(frm, text=record.instrument_name).grid(row=1, column=1, sticky="w", padx=5, pady=3)
        ttk.Label(frm, text="校准结果:").grid(row=2, column=0, sticky="e", padx=5, pady=3)
        ttk.Label(frm, text=record.result).grid(row=2, column=1, sticky="w", padx=5, pady=3)

        self.t_cert = _grid_label_text(frm, "证书摘要(补充)", 3,
                                       record.certificate_summary or "", height=3)
        self.t_comment = _grid_label_text(frm, "复核意见 *", 4, "", height=3)

        btns = ttk.Frame(frm)
        btns.grid(row=5, column=0, columnspan=2, pady=10)
        ttk.Button(btns, text="确认归档", command=self._ok).pack(side="left", padx=8)
        ttk.Button(btns, text="取消", command=self.destroy).pack(side="left", padx=8)

    def _ok(self):
        self.result = {
            "review_comment": _get_text_content(self.t_comment),
            "certificate_summary": _get_text_content(self.t_cert),
        }
        self.destroy()


class CancelDialog(tk.Toplevel):
    def __init__(self, master, record: CalibrationRecord):
        super().__init__(master)
        self.record = record
        self.result = None
        self.title("取消校准记录")
        self.resizable(False, False)
        self.transient(master)
        self.grab_set()

        frm = ttk.Frame(self, padding=15)
        frm.pack(fill="both", expand=True)

        msg = (f"确定取消记录？\n\n仪器编号: {record.instrument_code}\n"
               f"仪器名称: {record.instrument_name}\n状态: {record.status}")
        ttk.Label(frm, text=msg, justify="left").grid(row=0, column=0, columnspan=2,
                                                      padx=5, pady=8, sticky="w")
        self.t_reason = _grid_label_text(frm, "取消原因 *", 1, "", height=3)

        btns = ttk.Frame(frm)
        btns.grid(row=2, column=0, columnspan=2, pady=10)
        ttk.Button(btns, text="确认取消", command=self._ok).pack(side="left", padx=8)
        ttk.Button(btns, text="取消", command=self.destroy).pack(side="left", padx=8)

    def _ok(self):
        self.result = {"cancel_reason": _get_text_content(self.t_reason)}
        self.destroy()


class HistoryDialog(tk.Toplevel):
    def __init__(self, master, record: CalibrationRecord, history: List[TransitionLog],
                 summary: Dict[str, Any] = None):
        super().__init__(master)
        self.record = record
        self.history = history
        self.summary = summary
        self.title("状态流转历史与操作摘要")
        self.geometry("960x640")
        self.resizable(True, True)
        self.transient(master)
        self.grab_set()

        frm = ttk.Frame(self, padding=10)
        frm.pack(fill="both", expand=True)

        header = ttk.Frame(frm)
        header.pack(fill="x", pady=(0, 8))
        ttk.Label(header, text=f"仪器编号: {record.instrument_code}",
                  font=("", 11, "bold")).pack(side="left", padx=(0, 20))
        ttk.Label(header, text=f"仪器名称: {record.instrument_name}").pack(side="left", padx=(0, 20))
        status_info = get_status_info(record.status)
        status_color = status_info.get("color", "#2c3e50")
        ttk.Label(header, text=f"当前状态: {record.status}",
                  foreground=status_color, font=("", 10, "bold")).pack(side="left")

        if self.summary:
            self._build_summary_panel(frm)

        sep = ttk.Separator(frm, orient="horizontal")
        sep.pack(fill="x", pady=6)

        ttk.Label(frm, text="📜 状态流转历史日志（最新的在最下面）:",
                  font=("", 10, "bold")).pack(anchor="w", pady=(2, 4))

        cols = ("created_at", "action", "from_status", "to_status", "by_user", "reason", "is_undone")
        tree = ttk.Treeview(frm, columns=cols, show="headings")
        tree.heading("created_at", text="时间")
        tree.heading("action", text="操作")
        tree.heading("from_status", text="原状态")
        tree.heading("to_status", text="新状态")
        tree.heading("by_user", text="操作人")
        tree.heading("reason", text="原因/说明")
        tree.heading("is_undone", text="已撤销")
        tree.column("created_at", width=150, anchor="w")
        tree.column("action", width=110, anchor="w")
        tree.column("from_status", width=90, anchor="w")
        tree.column("to_status", width=90, anchor="w")
        tree.column("by_user", width=90, anchor="w")
        tree.column("reason", width=340, anchor="w")
        tree.column("is_undone", width=70, anchor="center")

        for log in history:
            undone = "✅是" if log.is_undone else ""
            tag = "undone" if log.is_undone else "normal"
            tree.insert("", "end", values=(log.created_at, log.action,
                        log.from_status, log.to_status, log.by_user,
                        log.reason, undone), tags=(tag,))
        tree.tag_configure("undone", foreground="#95a5a6", background="#f4f6f7")

        vsb = ttk.Scrollbar(frm, orient="vertical", command=tree.yview)
        tree.configure(yscrollcommand=vsb.set)

        tree_frame = ttk.Frame(frm)
        tree_frame.pack(fill="both", expand=True)
        tree.pack(side="left", fill="both", expand=True, in_=tree_frame)
        vsb.pack(side="right", fill="y", in_=tree_frame)

        btns = ttk.Frame(frm)
        btns.pack(fill="x", pady=10)
        ttk.Button(btns, text="关闭", command=self.destroy).pack(side="right", padx=8)

    def _build_summary_panel(self, parent):
        s = self.summary
        status_info = s.get("current_status_info", {})
        status_color = status_info.get("color", "#2c3e50")
        is_terminal = s.get("is_terminal", False)

        outer = ttk.LabelFrame(parent, text=" 📋 操作摘要 / 流转说明 ", padding=(10, 6))
        outer.pack(fill="x", pady=(0, 4))

        grid = ttk.Frame(outer)
        grid.pack(fill="x")

        ttk.Label(grid, text="当前状态:", font=("", 9, "bold")).grid(
            row=0, column=0, sticky="e", padx=4, pady=2)
        status_label = s.get("status_label", f"【{s['current_status']}】")
        ttk.Label(grid, text=status_label,
                  foreground=status_color, font=("", 10, "bold")).grid(
            row=0, column=1, sticky="w", padx=4, pady=2)

        ttk.Label(grid, text="状态说明:", font=("", 9)).grid(
            row=1, column=0, sticky="ne", padx=4, pady=2)
        ttk.Label(grid, text=status_info.get("description", ""),
                  wraplength=780, justify="left", foreground="#34495e").grid(
            row=1, column=1, sticky="w", padx=4, pady=2)

        ttk.Label(grid, text="为什么在这:", font=("", 9)).grid(
            row=2, column=0, sticky="ne", padx=4, pady=2)
        ttk.Label(grid, text=s.get("why_here", ""),
                  wraplength=780, justify="left", foreground="#5d6d7e").grid(
            row=2, column=1, sticky="w", padx=4, pady=2)

        ttk.Label(grid, text="流转统计:", font=("", 9)).grid(
            row=3, column=0, sticky="e", padx=4, pady=2)
        ttk.Label(grid, text=f"共 {s.get('history_count', 0)} 条流转记录，"
                             f"{s.get('undo_count', 0)} 条已撤销",
                  foreground="#5d6d7e").grid(
            row=3, column=1, sticky="w", padx=4, pady=2)

        undo_info = s.get("undo_info")
        ttk.Label(grid, text="撤销信息:", font=("", 9)).grid(
            row=4, column=0, sticky="ne", padx=4, pady=2)
        if undo_info and undo_info.get("is_terminal"):
            undo_text = (
                f"🔒 此记录处于【终态】\n"
                f"{undo_info.get('terminal_reason', '不可撤销')}"
            )
            undo_color = "#7f8c8d"
        elif undo_info:
            undo_text = (
                f"最近可撤销操作:「{undo_info['action']}」"
                f" (操作人: {undo_info['by_user']}, 时间: {undo_info['created_at']})\n"
                f"撤销后将返回:「{undo_info['undo_returns_to_status']}」"
                f" — {undo_info['undo_returns_to_description']}"
            )
            if undo_info.get("reason"):
                undo_text += f"\n原操作原因: {undo_info['reason']}"
            if undo_info.get("can_do"):
                undo_text += "\n✅ 当前【复核员】角色可执行撤销"
                undo_color = "#27ae60"
            elif undo_info.get("undo_role_missing"):
                undo_text += f"\n⚠️ 需要【{undo_info['required_role']}】权限，当前角色【{s.get('user_role', '?')}】无法撤销"
                undo_color = "#e67e22"
            else:
                undo_color = "#7f8c8d"
        else:
            undo_text = "无可撤销的流转操作（此状态为初始状态或已撤销到最早状态）"
            undo_color = "#7f8c8d"
        ttk.Label(grid, text=undo_text, wraplength=780,
                  justify="left", foreground=undo_color).grid(
            row=4, column=1, sticky="w", padx=4, pady=2)

        actions = s.get("available_actions", [])
        ttk.Label(grid, text="下一步操作:", font=("", 9)).grid(
            row=5, column=0, sticky="ne", padx=4, pady=2)
        if is_terminal:
            actions_text = f"🔒 当前为【终态】: {s.get('terminal_reason', '不可再执行任何流转操作，也不可撤销。')}"
        elif not actions:
            actions_text = "⏹ 当前状态无直接可执行的流转操作。可通过「撤销流转」回退到上一步（如有）。"
        else:
            action_parts = []
            for a in actions:
                if a.get("role_missing"):
                    role_tag = f"⚠️需【{a['required_role']}】权限"
                elif a.get("required_role"):
                    role_tag = f"🔒需【{a['required_role']}】权限"
                else:
                    role_tag = "🔓所有角色可操作"
                part = (
                    f"• 【{a['button_label']}】{role_tag}\n"
                    f"   说明: {a['description']}\n"
                    f"   执行后状态:「{a['to_status']}」— {a['to_status_description']}"
                )
                action_parts.append(part)
            actions_text = "\n\n".join(action_parts)
        ttk.Label(grid, text=actions_text, wraplength=780,
                  justify="left", foreground="#2c3e50").grid(
            row=5, column=1, sticky="w", padx=4, pady=2)
