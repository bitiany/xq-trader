# xqtrader 项目开发规则

## 流程

任务须完整闭环：**设计 → 规划 → 实施 → 质量测试 → 验收 → 总结**；测试子流程：**测试 → 修复 → 验收**。

## 原则（强制）

- 用户未明确要求时，**禁止兼容/过渡/降级实现**（旧 API、双轨逻辑、别名、兜底、workaround 等）；按推荐方案一次性改到位
- **禁止** fallback、静默吞异常、伪代码占位；**禁止**用 mock 替代真实实现（**未实现功能及明确标注的占位除外**）
- **禁止**未经用户允许执行 `git commit` / `git push`
- **禁止**未经允许生成报告、总结等文件

## 质量检查

变更后须完成：mypy 类型检查、ruff 静态检查、逻辑自查；均**禁止** `--fix` 自动修复。

```powershell
ruff check src/ tests/
mypy src/
```

## 测试

- **黑盒为主、单测为辅**；代码变更须**重启服务**后做 **API 黑盒测试**
- pytest + pytest-asyncio；fixture 与环境初始化统一在 `conftest.py`
- 异步：`@pytest_asyncio.fixture`；`@pytest.mark.asyncio(loop_scope="session")`

## 代码约定

- 业务代码在 `src/`，导入 `from framework.xxx import ...`
- ORM 继承 `Base` / `AuditedBase`，CRUD 遵循 dal-orm skill；**禁止主外键关系**
- 数据源见 `datasource.yml`（`${ENV_VAR}` 读 `.env`）
- 查库验证、改表结构须用 **db-tools**

## 架构与设计（强制）

- **高内聚松耦合**：模块/类职责单一、边界清晰；跨模块交互通过公共接口，**禁止**访问其他模块私有属性
- **面向对象**：状态与行为封装为类，**禁止**散装函数模块；共享实例通过类属性或模块级单例管理，**禁止**各处重复创建
- **职责单一**：一个模块/类只承担一类职责，超职责须拆分
- **策略模式**：条件分支逻辑须封装为策略类 + 注册表，**禁止**长串 `if/elif`

## 代码质量（禁止项）

- **禁止死代码**：未使用的变量、方法、属性，发现即删除
- **禁止局部导入**：除延迟加载或循环依赖外，导入必须在文件顶部
- **禁止 print()**：所有输出使用 `logger`
- **禁止 logger.error 无堆栈**：`logger.error` 必须添加 `exc_info=True` 参数，打印异常堆栈信息
- **禁止重复逻辑**：同一逻辑须提取为共享方法，禁止各处重复实现
- **禁止 asyncio.run()**：异步上下文中禁止嵌套事件循环
- **禁止上帝代码**：函数/类职责过多须拆分，单个函数体不超过 80 行；类方法数不做硬性限制，但须保持职责单一

## 环境与命令

- **Windows + PowerShell**；命令用 `;` 分隔；HTTP 用 `Invoke-RestMethod`；环境变量 `$env:KEY="value"`
- 激活虚拟环境：`conda activate .\.conda`
- 启动服务见 [README.md](README.md)；**禁止**随意编写包装类测试脚本
