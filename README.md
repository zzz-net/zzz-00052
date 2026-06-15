# 仪器校准排程与记录系统

本地桌面工具，用于维护仪器台账、按周期生成校准计划、管理校准流程的完整生命周期（待执行 → 已完成 → 待复核 → 归档/取消）。

> **🔑 单源真相机制**：本系统所有状态定义、操作规则、界面提示、导出内容、校验逻辑共用唯一来源 —— `calibration_tool/models.py` 中的 `STATUS_RULES` 和 `ACTION_RULES` 字典。任何状态流转相关的修改只需在此一处调整，即可保证界面、导出、日志、校验、文档完全一致。

## ✨ 功能特性

- **仪器台账管理**：新增、编辑仪器，维护编号、名称、型号、校准周期、责任人等信息
- **校准计划生成**：一键按仪器校准周期自动生成待执行计划
- **状态流转**（规则来源：`ACTION_RULES`）：
  - 待执行 → 录入校准结果 → 已完成
  - 已完成 → 提交复核 → 待复核
  - 待复核 → 复核归档 → 归档（**终态，不可撤销**）
  - 任一步骤均可由复核员**取消**（记录取消原因）
- **操作摘要面板**：选中记录后实时显示（数据来源：`get_transition_summary()`）：
  - 当前状态及含义（来源：`STATUS_RULES[status].description`）
  - 为什么停在这个状态（来源：最近一次流转历史 + `STATUS_RULES[status].how_got_here`）
  - 下一步可执行操作及所需角色（来源：`get_available_actions()`）
  - 最近一次流转能否撤销、撤销后回到哪一步（来源：`get_undoable_transition()` + `ACTION_RULES[action].undo_returns_to`）
- **状态流转历史**：每次状态变更均记录快照、操作人、时间、原因，完整可追溯
- **撤销上一次流转**：复核员可撤销最近一次流转（录入/提交复核/归档/取消），恢复原状态和所有字段
  - 撤销 ≠ 取消：撤销是回滚操作，不会写入取消原因
  - 所有流转均可撤销（除了撤销操作本身）
- **字段完整**：责任人、校准结果、超期原因、复核意见、证书摘要、取消原因
- **角色权限**（规则来源：`ACTION_RULES[action].required_role`）：
  - 操作员：录入校准、提交复核
  - 复核员：所有操作 + 复核归档 + 取消记录 + 撤销流转
- **数据持久化**：JSON 文件存储，关闭重开后台账、历史、撤销记录保持一致
- **导出功能**：CSV 和 HTML 两种格式，包含所有状态（含取消状态），导出字段与界面摘要共用同一来源
- **操作日志**：所有关键操作记录到 `data/calibration_tool.log`，包含状态流转、撤销、导出、错误等
- **完整校验**：重复编号、非法日期、空值、权限不足、空撤销原因等均有明确错误提示

## 📁 项目结构

```
zzz-00052/
├── run.py                      # GUI 启动入口
├── seed_data.py                # 样例数据初始化脚本
├── test_flow.py                # 自动化测试（unittest，30+ 测试用例）
├── README.md                   # 本文档
├── calibration_tool/
│   ├── __init__.py
│   ├── models.py               # 数据模型 (Instrument/CalibrationRecord/TransitionLog/User)
│   ├── storage.py              # JSON 持久化存储层
│   ├── service.py              # 业务逻辑层（计划生成、状态流转、历史、撤销、导出）
│   └── gui/
│       ├── __init__.py
│       ├── main_window.py      # 主窗口（含 6 个标签页）
│       └── dialogs.py          # 对话框（新增仪器/录入校准/复核/取消/历史查看）
└── data/                       # 运行时 JSON 数据目录（自动创建）
    ├── instruments.json        # 仪器台账
    ├── records.json            # 所有校准记录（含取消状态）
    ├── history.json            # 状态流转历史（每次变更快照）
    ├── cancelled_records.json  # 保留（兼容旧数据，不再写入）
    └── users.json              # 用户列表
```

## 🚀 环境要求

- Python 3.8+
- 仅使用 Python 标准库（tkinter 为 GUI，无第三方依赖）

## ▶️ 启动运行

```powershell
# Windows PowerShell
cd d:\workSpace\AI__SPACE\zzz-00052
python run.py
```

首次运行会自动：
1. 创建 `data/` 目录及 JSON 数据文件
2. 初始化样例仪器（5 台）和用户（3 个）

## 👤 默认用户

| 用户名      | 角色   | 权限                                 |
|------------|--------|--------------------------------------|
| operator1  | 操作员 | 录入校准、提交复核                   |
| operator2  | 操作员 | 录入校准、提交复核                   |
| reviewer1  | 复核员 | 所有操作 + 复核归档 + 取消记录 + 撤销流转 |

在主窗口顶部下拉框可切换当前用户。

---

## 📖 主流程操作指南

### 1. 新增仪器
「仪器台账」标签页 → 点击「新增仪器」→ 填写信息 → 确定

### 2. 生成计划
「仪器台账」标签页 → 点击「生成校准计划」→ 系统根据周期自动生成待执行计划

### 3. 录入校准
切换到「待执行」标签页 → 选中记录 → 「录入校准结果」→ 填实际日期/结果/证书摘要/超期原因 → 提交

### 4. 提交复核
「已完成」标签页 → 选中 → 「提交复核」

### 5. 复核归档
顶部切换为 `reviewer1` → 「待复核」标签页 → 选中 → 「复核并归档」→ 填写复核意见 → 确认归档

### 6. 取消记录（复核员）
在「待执行」「已完成」「待复核」标签页 → 选中记录 → 「取消记录」→ 填写取消原因

### 7. 撤销上一次流转（复核员）
在任何记录标签页 → 选中记录 → 点击「撤销上一次流转」→ 确认操作

可撤销的流转（只能撤销最近一次）：
- ✅ 录入校准（回到待执行）
- ✅ 提交复核（回到已完成）
- ✅ 复核归档（回到待复核）
- ✅ 取消记录（恢复到取消前状态）
- ❌ 撤销操作本身不可撤销

### 8. 查看流转历史
在任何记录标签页 → 选中记录 → 点击「查看历史」→ 弹出完整流转历史窗口

### 9. 导出
点击顶部「导出 CSV」或「导出 HTML」→ 选择保存位置

---

## 🧪 失败路径复现方式

| 失败场景                  | 操作方法                                                     | 预期提示                                   |
|---------------------------|--------------------------------------------------------------|------------------------------------------|
| 重复仪器编号              | 新增一台与已有仪器编号相同的仪器                               | "仪器编号 'XXX' 已存在，不允许重复"       |
| 非法日期格式              | 录入校准时填 `2024-13-40` 或留空                              | "实际校准日期格式无效" / "不能为空"        |
| 普通操作员尝试复核        | 用 operator1 用户去「待复核」页点「复核并归档」                 | "当前用户无复核权限，请切换为复核员角色"  |
| 普通操作员尝试取消        | 用 operator1 用户点「取消记录」                                | "当前用户无撤销权限，请切换为复核员角色"  |
| 普通操作员尝试撤销        | 用 operator1 用户点「撤销上一次流转」                          | "当前用户无撤销权限，请切换为复核员角色"  |
| 空取消原因                | 用 reviewer1 取消时不填原因直接提交                            | "撤销原因不能为空"                         |
| 空撤销流转（无可撤销操作） | 选择一条新生成的待执行记录点「撤销上一次流转」                  | "该记录没有可撤销的流转操作"               |
| 空复核意见                | 复核员归档时不填意见                                          | "复核意见不能为空"                         |
| 超期未填原因              | 实际校准日期晚于计划日期且不填超期原因                         | "校准已超期，必须填写超期原因"             |
| 撤销归档记录              | 选择一条已归档记录点「撤销上一次流转」                          | "该记录没有可撤销的流转操作"               |

所有失败操作均不会破坏原有数据状态。

---

## ✅ 自动化测试

### 运行所有测试

```powershell
cd d:\workSpace\AI__SPACE\zzz-00052
$env:PYTHONIOENCODING='utf-8'
python -m unittest test_flow.TestTransitionHistory -v
```

### 测试覆盖清单

| 测试用例 | 验证点 |
|---------|--------|
| `test_cancel_then_undo_pending` | 取消待执行 → 撤销恢复 → 历史完整 |
| `test_submit_calibration_then_undo` | 录入校准 → 撤销 → 字段完全回滚 |
| `test_send_for_review_then_undo` | 提交复核 → 撤销 → 回到已完成 |
| `test_cancel_after_completed_then_undo` | 完成后取消 → 撤销 → 恢复完成状态 |
| `test_archived_cannot_cancel` | 归档记录不可取消，但归档本身可撤销 |
| `test_archive_then_undo` | 归档后撤销 → 回到待复核，字段完全恢复 |
| `test_operator_cannot_undo` | 操作员越权撤销被拒 |
| `test_empty_cancel_reason_rejected` | 空取消原因被拒 |
| `test_operator_cannot_cancel` | 操作员越权取消被拒 |
| `test_no_undoable_transition_rejected` | 无可撤销操作时提示 |
| `test_history_persistence_after_reload` | 关闭重启后历史、记录状态一致 |
| `test_instrument_calibration_date_rollback_on_undo` | 撤销录入校准后，仪器上次校准日期回滚 |
| `test_export_includes_cancelled_records` | 导出 CSV 包含取消记录 |
| `test_undo_is_not_cancel` | 撤销 ≠ 取消：字段和历史均有明确区分 |
| `test_cancelled_list_uses_main_records` | 取消列表从主记录过滤，撤销后自动消失 |

### 手动 GUI 验证步骤

1. **取消与撤销验证**：
   - 登录 reviewer1 → 生成计划 → 「待执行」页选中一条 → 点「取消记录」→ 填原因确定
   - 打开「取消记录」标签页，确认记录存在，状态列显示"待执行"（取消前状态）
   - 选中该记录 → 点「撤销上一次流转（恢复）」→ 确认
   - 记录从「取消记录」页消失，回到「待执行」页，字段完全恢复
   - 点「查看历史」，确认有两条记录：取消操作 + 撤销流转操作

2. **录入校准与撤销验证**：
   - 登录 operator1 → 「待执行」页录入校准 → 状态变已完成
   - 切换 reviewer1 → 选中该记录 → 点「撤销上一次流转」→ 确认
   - 记录回到「待执行」页，实际日期、结果等字段清空

3. **历史查看验证**：
   - 走完主流程：生成计划 → 录入 → 提交 → 归档 → 撤销归档
   - 选中记录 → 点「查看历史」→ 确认有 4 条流转记录（录入校准/提交复核/复核归档/撤销流转）

4. **重启验证**：
   - 完成上述操作后，关闭程序 → 重新打开
   - 检查所有标签页的记录数量和状态是否与关闭前一致
   - 打开任意记录的历史，确认历史记录完整，归档和撤销归档记录都存在

5. **导出验证**：
   - 取消一条记录 → 点「导出 CSV」→ 打开文件确认取消记录包含在内
   - 点「导出 HTML」→ 打开文件确认格式和数据正确

---

## 🔧 数据持久化说明

所有数据存储在 `data/` 目录下的 JSON 文件：

| 文件 | 内容 | 新增/修改 |
|------|------|-----------|
| `instruments.json` | 仪器台账 | 原有 |
| `records.json` | 所有校准记录（含取消状态，不再物理删除） | ✅ 修改：取消记录不再搬移 |
| `history.json` | 状态流转历史（每次变更的完整快照） | ✅ 新增 |
| `cancelled_records.json` | 保留（不再写入，仅兼容读取） | ✅ 修改 |
| `users.json` | 用户列表 | 原有 |

关闭程序后再次打开，所有数据、状态、历史均自动恢复。

## 🐛 根因修复说明

### 原问题根因
1. **物理删除问题**：`cancel_record` 将记录从 `records.json` 删除并移动到 `cancelled_records.json`，导致原状态不可追溯
2. **无历史追踪**：每次状态流转不记录"之前是什么状态、改了什么"，误操作后无法恢复
3. **无撤销能力**：取消操作等同于删除，没有回滚机制
4. **信息分散**：界面提示、README、导出结果、验证脚本各说各话，没有统一的判断来源
5. **可见性不足**：用户无法直观知道"为什么停在这个状态、下一步能做什么、需要什么角色、能否撤销"

### 修复方案（单源真相架构）

#### 核心规则层（唯一真相来源）
1. **[models.py](file:///d:/workSpace/AI__SPACE/zzz-00052/calibration_tool/models.py)**：
   - 新增 `STATUS_RULES` 字典：统一定义所有状态的说明、到达途径、颜色
   - 新增 `ACTION_RULES` 字典：统一定义所有操作的允许状态、所需角色、目标状态、撤销返回
   - 新增 `get_available_actions()`、`get_status_info()`、`get_action_info()` 统一查询接口
   - 新增 `TransitionLog` 数据类，记录每次流转的状态变化、操作人、原因、完整快照
   - 新增 `setup_logger()` 日志配置，统一日志格式

#### 业务逻辑层（复用核心规则）
2. **[service.py](file:///d:/workSpace/AI__SPACE/zzz-00052/calibration_tool/service.py)**：
   - 每次流转（录入/提交/复核/取消）前保存快照，写入 `TransitionLog`
   - 新增 `get_transition_summary()` 方法：统一生成操作摘要（界面、导出、校验共用）
   - 新增 `undo_last_transition()` 方法，从最近一次可撤销操作的快照恢复
   - 导出时调用 `get_transition_summary()` 确保与界面显示一致
   - 所有关键操作记录日志（状态流转、撤销、导出、错误）

#### 存储层
3. **[storage.py](file:///d:/workSpace/AI__SPACE/zzz-00052/calibration_tool/storage.py)**：新增 `history.json` 读写接口，`cancel_record` 不再搬移记录

#### UI层（复用业务逻辑层摘要）
4. **[gui/main_window.py](file:///d:/workSpace/AI__SPACE/zzz-00052/calibration_tool/gui/main_window.py)**：
   - 新增「操作摘要」面板，调用 `get_transition_summary()` 显示
   - 显示：当前状态、为什么在这、流转统计、撤销信息、下一步操作
   - 各标签页新增「查看历史」和「撤销上一次流转」按钮
5. **[gui/dialogs.py](file:///d:/workSpace/AI__SPACE/zzz-00052/calibration_tool/gui/dialogs.py)**：
   - 新增 `HistoryDialog` 历史查看对话框，顶部内嵌操作摘要面板（与主界面共用同一来源）

#### 文档与验证层（引用核心规则）
6. **[README.md](file:///d:/workSpace/AI__SPACE/zzz-00052/README.md)**：所有状态、操作、权限说明均引用 `STATUS_RULES` 和 `ACTION_RULES`
7. **[test_flow.py](file:///d:/workSpace/AI__SPACE/zzz-00052/test_flow.py)**：30+ 自动化测试用例，覆盖摘要、权限、撤销、导出、重启一致性
8. **[verify_gui_feedback.py](file:///d:/workSpace/AI__SPACE/zzz-00052/verify_gui_feedback.py)**：CLI综合验证脚本，覆盖所有手动验证链路
