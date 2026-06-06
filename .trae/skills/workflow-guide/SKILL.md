---
name: "workflow-guide"
description: "工作流业务使用指南。当用户需要创建、配置、调用工作流，或涉及工作流JSON配置、API调用、节点类型、变量引用等业务侧使用问题时，必须遵循本 skill。"
---

# 工作流业务使用指南

本指南面向业务开发者，介绍如何通过 JSON 配置定义工作流，以及如何通过 API 启动、查询、恢复和停止工作流。

---

## 一、快速开始

### 1. 创建工作流配置文件

在项目 `flow/` 目录下创建 JSON 文件，文件名即为 `flow_id`。例如 `flow/my_task.json` 的 flow_id 为 `my_task`。

### 2. 最简工作流示例

```json
{
  "id": "my_task",
  "description": "我的第一个工作流",
  "input_schema": { "input_value": "input_value" },
  "output_schema": { "result": "tool_a" },
  "graph": {
    "nodes": [
      { "id": "start", "type": "start", "name": "开始", "props": { "variables": [{"variable": "input_value"}] } },
      { "id": "tool_a", "type": "tool", "name": "处理", "props": { "name": "echo_tool", "class": "xxx.EchoTool", "variables": [{"variable": "text", "value": "{input_value}", "type": "text"}] } },
      { "id": "end", "type": "end", "name": "结束", "props": { "output": "{tool_a}" } }
    ],
    "edges": [
      {"from": "start", "to": "tool_a"},
      {"from": "tool_a", "to": "end"}
    ]
  }
}
```

### 3. 通过 API 启动

```bash
POST /api/v1/workflow/run
{
  "flow_id": "my_task",
  "inputs": {"input_value": "hello"}
}
```

---

## 二、配置文件结构

工作流 JSON 配置由以下顶层字段组成：

| 字段 | 必填 | 说明 |
|------|------|------|
| `id` | 是 | 工作流唯一标识，对应文件名（不含 .json） |
| `description` | 否 | 工作流描述 |
| `input_schema` | 否 | 声明输入参数名及类型，如 `{"input_value": "input_value"}` |
| `output_schema` | 否 | 声明输出字段与变量映射，如 `{"result": "tool_a"}` |
| `graph` | 是 | 工作流图定义，包含 nodes 和 edges |

---

## 三、节点类型

### 3.1 Start 节点（开始）

工作流入口，每个工作流有且仅有一个。

```json
{
  "id": "start",
  "type": "start",
  "name": "开始",
  "props": {
    "variables": [
      {"variable": "input_value"}
    ]
  }
}
```

- `variables`：声明工作流接收的输入参数名

### 3.2 End 节点（结束）

工作流出口，必须配置 `output` 模板指定输出内容。

```json
{
  "id": "end",
  "type": "end",
  "name": "结束",
  "props": {
    "output": "{tool_a}"
  }
}
```

- `output`：使用 `{变量名}` 引用上游节点输出，支持拼接如 `"{a}_{b}"`

### 3.3 Tool 节点（工具调用）

执行外部工具，结果以节点 id 为 key 存入变量。

```json
{
  "id": "tool_a",
  "type": "tool",
  "name": "数据处理",
  "props": {
    "name": "echo_tool",
    "class": "xxx.EchoTool",
    "variables": [
      {"variable": "text", "value": "{input_value}", "type": "text"},
      {"variable": "count", "value": "10", "type": "text"}
    ]
  }
}
```

| 字段 | 说明 |
|------|------|
| `name` | 工具注册名 |
| `class` | 工具类完整路径（模块.类名） |
| `variables` | 传入工具的参数列表，`value` 支持 `{变量名}` 引用 |

**变量引用规则**：`{节点id}` 引用该节点的输出结果。例如 `{tool_a}` 引用 id 为 `tool_a` 的节点输出。

### 3.4 Switch 节点（分支路由）

根据条件选择不同分支执行，类似 if/else。

```json
{
  "id": "switch",
  "type": "switch",
  "name": "分支路由",
  "props": {
    "case": [
      {
        "id": "approve_path",
        "condition": { "type": "equals", "variable": "{review__action}", "value": "approve" }
      },
      {
        "id": "reject_path",
        "condition": { "type": "equals", "variable": "{review__action}", "value": "reject" }
      }
    ]
  }
}
```

**条件类型**：

| type | 说明 | 示例 |
|------|------|------|
| `equals` | 等于 | `{"type": "equals", "variable": "{x}", "value": "yes"}` |
| `not-equals` | 不等于 | `{"type": "not-equals", "variable": "{x}", "value": "no"}` |
| `greater-than` | 大于 | `{"type": "greater-than", "variable": "{score}", "value": "80"}` |
| `less-than` | 小于 | `{"type": "less-than", "variable": "{score}", "value": "60"}` |
| `contains` | 包含 | `{"type": "contains", "variable": "{text}", "value": "ok"}` |
| `not-null` | 非空 | `{"type": "not-null", "variable": "{x}"}` |
| `null` | 为空 | `{"type": "null", "variable": "{x}"}` |
| `true` | 为真 | `{"type": "true", "variable": "{flag}"}` |
| `false` | 为假 | `{"type": "false", "variable": "{flag}"}` |

**重要**：Switch 节点必须至少匹配一个分支，否则工作流将报错终止。

**特殊变量引用**：`{节点id__action}` 获取 HumanInput 节点的用户动作（approve/reject 等）。

### 3.5 HumanInput 节点（人工确认）

暂停工作流等待用户操作，支持表单和动作按钮。

```json
{
  "id": "review",
  "type": "human_input",
  "name": "人工审阅",
  "props": {
    "form": {
      "title": "请审阅",
      "description": "确认结果是否正确",
      "fields": [
        {"name": "confirmed", "type": "select", "label": "确认", "options_source": "{tool_a}", "multiple": false},
        {"name": "comment", "type": "text", "label": "备注", "required": false}
      ]
    },
    "actions": [
      {"id": "approve", "label": "确认", "style": "primary"},
      {"id": "reject", "label": "拒绝", "style": "danger"}
    ],
    "timeout": {
      "seconds": 3600,
      "default_action": "reject"
    }
  }
}
```

| 字段 | 说明 |
|------|------|
| `form.title` | 表单标题 |
| `form.description` | 表单描述 |
| `form.fields` | 表单字段列表 |
| `form.fields[].name` | 字段名 |
| `form.fields[].type` | 字段类型：`text`、`select` |
| `form.fields[].label` | 显示标签 |
| `form.fields[].required` | 是否必填，默认 true |
| `form.fields[].options_source` | 下拉选项数据源，支持 `{变量名}` 引用 |
| `form.fields[].multiple` | 是否多选，默认 false |
| `actions` | 动作按钮列表 |
| `actions[].id` | 动作标识，用于 Switch 路由 |
| `actions[].label` | 按钮显示文本 |
| `actions[].style` | 按钮样式：`primary`、`danger`、`default` |
| `timeout.seconds` | 超时秒数 |
| `timeout.default_action` | 超时后自动执行的动作 id |

**输出变量**：
- `{review}` → 用户填写的表单数据（dict）
- `{review__action}` → 用户选择的动作 id（如 `"approve"`）

### 3.6 SubGraph 节点（子工作流）

嵌套另一个工作流作为子流程。

```json
{
  "id": "sub_task",
  "type": "subgraph",
  "name": "子流程",
  "props": {
    "flow_id": "another_workflow"
  }
}
```

---

## 四、边（Edges）— 节点连接

### 4.1 串行连接

```json
{"from": "start", "to": "tool_a"}
```

### 4.2 并行分支

一个节点有多条出边即为并行，需标记 `"type": "parallel"`：

```json
{"from": "start", "to": "tool_a", "type": "parallel"},
{"from": "start", "to": "tool_b", "type": "parallel"},
{"from": "start", "to": "tool_c", "type": "parallel"}
```

并行分支同时执行，结果以各自节点 id 为 key 存储，互不覆盖。汇聚节点（fan-in）自动等待所有并行分支完成后执行。

### 4.3 条件分支

Switch 节点的出边需标记 `condition` 匹配 case id：

```json
{"from": "switch", "to": "approve_path", "condition": "approve_path"},
{"from": "switch", "to": "reject_path", "condition": "reject_path"}
```

---

## 五、变量引用规则

工作流中通过 `{变量名}` 语法引用数据：

| 引用方式 | 含义 | 示例 |
|----------|------|------|
| `{input_value}` | Start 节点声明的输入参数 | `"{input_value}"` |
| `{节点id}` | 该节点的输出结果 | `"{tool_a}"` |
| `{节点id__action}` | HumanInput 节点的用户动作 | `"{review__action}"` |

**拼接**：支持多个变量拼接，如 `"APPROVED_{tool_a}"` 或 `"{a}_{b}"`。

**并行安全**：并行分支中，各节点输出以节点 id 为 key 隔离，同名工具不会互相覆盖。

---

## 六、API 接口

### 6.1 启动工作流

```
POST /api/v1/workflow/run
```

请求体：
```json
{
  "flow_id": "my_task",
  "inputs": {"input_value": "hello"},
  "workspace_id": ""
}
```

响应：
```json
{
  "run_id": "run_20260606_xxxx",
  "flow_id": "my_task",
  "status": "succeeded",
  "outputs": {"tool_a": "hello"},
  "elapsed_time": 0.03
}
```

### 6.2 查询执行状态

```
GET /api/v1/workflow/run/{run_id}
```

响应字段：

| 字段 | 说明 |
|------|------|
| `run_id` | 执行记录 ID |
| `flow_id` | 工作流 ID |
| `status` | 状态：`running` / `succeeded` / `failed` / `paused` / `stopped` |
| `outputs` | 输出结果（succeeded 时） |
| `interrupt` | 中断信息（paused 时） |
| `error` | 错误信息（failed 时） |
| `current_node_id` | 当前节点 ID |
| `current_node_title` | 当前节点标题 |
| `total_steps` | 总步骤数 |
| `elapsed_time` | 耗时（秒） |

### 6.3 恢复中断的工作流

当工作流在 HumanInput 节点暂停时，通过此接口恢复：

```
POST /api/v1/workflow/run/{run_id}/resume
```

请求体：
```json
{
  "resume_value": {
    "action": "approve",
    "form_data": {"confirmed": "yes", "comment": "looks good"}
  }
}
```

| 字段 | 必填 | 说明 |
|------|------|------|
| `action` | 是 | 用户选择的动作 id，对应 HumanInput 节点 actions 配置 |
| `form_data` | 是 | 用户填写的表单数据 |

### 6.4 停止工作流

```
POST /api/v1/workflow/run/{run_id}/stop
```

仅 `running` 和 `paused` 状态可停止。

### 6.5 列出可用工作流

```
GET /api/v1/workflow/list
```

响应：
```json
[
  {"flow_id": "my_task", "name": "my_task", "description": "我的第一个工作流"}
]
```

---

## 七、典型流程模板

### 7.1 串行流程

```
start → tool_a → tool_b → end
```

适用于：数据处理管道、多步骤顺序执行。

### 7.2 并行流程

```
start → [tool_a, tool_b, tool_c] → merge → end
```

适用于：多数据源并行采集、多维度并行计算后汇总。

### 7.3 人工确认流程

```
start → tool_a → review(HumanInput) → end
```

适用于：需要人工审批、确认后才能继续的场景。

### 7.4 分支路由流程

```
start → tool_a → review → switch → [approve_path / reject_path] → end
```

适用于：根据人工审批结果走不同处理路径。

### 7.5 完整示例：人工审批 + 分支

```json
{
  "id": "approval_flow",
  "description": "人工审批流程",
  "input_schema": {"input_value": "input_value"},
  "output_schema": {"result": "approve_path"},
  "graph": {
    "nodes": [
      {"id": "start", "type": "start", "name": "开始", "props": {"variables": [{"variable": "input_value"}]}},
      {"id": "analyze", "type": "tool", "name": "分析", "props": {"name": "analyze_tool", "class": "xxx.AnalyzeTool", "variables": [{"variable": "data", "value": "{input_value}", "type": "text"}]}},
      {"id": "review", "type": "human_input", "name": "人工审批", "props": {"form": {"title": "审批", "fields": [{"name": "comment", "type": "text", "label": "审批意见", "required": false}]}, "actions": [{"id": "approve", "label": "通过", "style": "primary"}, {"id": "reject", "label": "驳回", "style": "danger"}], "timeout": {"seconds": 3600, "default_action": "reject"}}},
      {"id": "switch", "type": "switch", "name": "路由", "props": {"case": [{"id": "approve_path", "condition": {"type": "equals", "variable": "{review__action}", "value": "approve"}}, {"id": "reject_path", "condition": {"type": "equals", "variable": "{review__action}", "value": "reject"}}]}},
      {"id": "approve_path", "type": "tool", "name": "执行", "props": {"name": "exec_tool", "class": "xxx.ExecTool", "variables": [{"variable": "data", "value": "{analyze}", "type": "text"}]}},
      {"id": "reject_path", "type": "tool", "name": "记录驳回", "props": {"name": "log_tool", "class": "xxx.LogTool", "variables": [{"variable": "reason", "value": "{review}", "type": "text"}]}},
      {"id": "end", "type": "end", "name": "结束", "props": {"output": "{approve_path}{reject_path}"}}
    ],
    "edges": [
      {"from": "start", "to": "analyze"},
      {"from": "analyze", "to": "review"},
      {"from": "review", "to": "switch"},
      {"from": "switch", "to": "approve_path", "condition": "approve_path"},
      {"from": "switch", "to": "reject_path", "condition": "reject_path"},
      {"from": "approve_path", "to": "end"},
      {"from": "reject_path", "to": "end"}
    ]
  }
}
```

---

## 八、注意事项

1. **End 节点必须配置 output**：`output` 字段使用 `{变量名}` 指定工作流最终输出内容，未配置则输出为空
2. **Switch 必须匹配**：所有 case 都不匹配时工作流报错终止，请确保覆盖所有可能的情况
3. **HumanInput resume 必须是 dict**：`resume_value` 必须包含 `action`（字符串）和 `form_data`（字典），非 dict 格式将报错
4. **并行分支用节点 id 引用**：并行分支中各节点结果以节点 id 为 key，通过 `{节点id}` 引用，不要依赖工具名
5. **变量引用用花括号**：所有变量引用统一使用 `{变量名}` 语法，支持拼接
6. **flow_id 即文件名**：配置文件放在 `flow/` 目录，文件名（去掉 .json）就是 flow_id
