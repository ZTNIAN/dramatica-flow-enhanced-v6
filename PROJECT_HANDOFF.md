# Dramatica-Flow Enhanced V6 — 项目交接文档

> 最后更新：2026-04-17
> 版本：V6（V5 基础上修复端点 + 自适应审查 + MiroFish 闭环 + Token追踪 + KB热加载 + 错误恢复）
> 本文档面向所有人，尤其是零基础用户。读完就能理解整个项目、怎么用、怎么继续迭代。

---

## 一、这是什么？

**Dramatica-Flow Enhanced** 是一个 **AI 自动写小说系统**。你给它一句话设定，它帮你：

1. **市场分析** — 分析目标读者偏好（引用番茄小说真实数据）
2. **构建世界观** — 角色/势力/地点/规则，全部自动生成
3. **角色成长规划** — 每个主要角色8维档案 + 成长弧线 + 转折点
4. **情绪曲线设计** — 整书情绪起伏规划，精确操控读者情绪
5. **生成大纲** — 三幕结构 + 逐章规划 + 张力曲线
6. **自动写作** — 一章一章写，每章2000-4000字
7. **多维审查** — 对话/场景/心理/风格，4个专项审查Agent
8. **自动审计** — 9维度加权评分 + 17条红线一票否决
9. **审查→修订闭环** — 所有审查问题合并进修订循环
10. **MiroFish读者测试** — 每5章模拟1000名读者反馈 → 反馈注入下一章
11. **Agent能力画像** — 追踪每个Agent的工作质量
12. **Token费用追踪** — 精确到每章每Agent的LLM消耗
13. **知识库热加载** — 改了知识库文件立即生效，不用重启
14. **错误恢复** — 写作中断后可从checkpoint恢复

**V6 一句话：V5 的基础上修复了坏了的Web端点、让自适应审查真正智能、MiroFish反馈形成闭环、随时知道花了多少钱、改知识库不用重启。**

---

## 二、项目地址

| 版本 | 地址 | 说明 |
|------|------|------|
| **原版** | https://github.com/ydsgangge-ux/dramatica-flow | 叙事逻辑强，但缺乏前期规划和质量管控 |
| **V1-V4** | ... | （历史版本，见V5交接文档） |
| **V5** | https://github.com/ZTNIAN/dramatica-flow-enhanced-v5 | 多LLM+选择性审查+WebSocket+Agent画像 |
| **V6（当前）** | https://github.com/ZTNIAN/dramatica-flow-enhanced-v6 | 修复端点+自适应审查+闭环+追踪+热加载+恢复 |

---

## 三、V5 → V6 的区别

### V6 修复了什么

| 优先级 | 问题 | 改动文件 | 说明 |
|--------|------|----------|------|
| P1-1 | 端到端测试 | 待做 | 需实际部署验证 |
| P1-2 | writing router 构造器 | `core/server/routers/writing.py` | **完全重写**：正确构造 WritingPipeline，修复所有端点路由 |
| P1-3 | 低分触发全量审查 | `core/pipeline.py` | 增强 adaptive 模式：最近3章有低分或连续2章需修订 → 全量审查 |
| P2-4 | MiroFish 闭环 | `core/pipeline.py` | 加载最近一次读者测试反馈，注入建筑师上下文 |
| P2-5 | Token 追踪 | `core/token_tracker.py`（新） | 按Agent/章节/model追踪token消耗+费用估算 |
| P2-6 | KB 热加载 | `core/agents/kb.py` | 懒加载+文件修改时间检测+API端点触发重载 |
| P2-7 | 错误恢复 | `core/server/routers/writing.py` | Checkpoint机制：中断后保存进度，/resume端点恢复 |

### V6 新增文件

| 文件 | 说明 |
|------|------|
| `core/token_tracker.py` | Token使用追踪器（按Agent/章节/model聚合+费用估算） |

### V6 修改文件

| 文件 | 改动 |
|------|------|
| `core/server/routers/writing.py` | **完全重写**：修复 Pipeline 构造、路由路径、审计参数；新增 checkpoint/resume 端点 |
| `core/server/routers/enhanced.py` | 新增 token-usage / reload-kb / kb-status 端点；修复模板语法 |
| `core/pipeline.py` | 增强 adaptive 审查（低分触发）；MiroFish 反馈注入；Token 统计保存 |
| `core/llm/__init__.py` | 新增 TrackedProvider 装饰器（自动追踪token） |
| `core/agents/kb.py` | 重写：懒加载 + 缓存 + 文件修改检测 + reload 函数 |
| `.env.example` | 补齐 V6 配置说明 |

### V6 新增 API 端点

| 端点 | 方法 | 说明 |
|------|------|------|
| `/api/books/{id}/token-usage` | GET | Token 使用量和费用估算 |
| `/api/books/reload-kb` | POST | 热加载知识库文件 |
| `/api/books/kb-status` | GET | 检查知识库文件更新状态 |
| `/api/books/{id}/checkpoint` | GET | 查看当前 checkpoint 状态 |
| `/api/books/{id}/resume` | POST | 从 checkpoint 恢复写作 |
| `/api/books/{id}/revise` | POST | 修订端点（路径修复，原 /api/action/revise） |
| `/api/books/{id}/write` | POST | 写作端点（路径修复，原 /api/action/write） |
| `/api/books/{id}/audit` | POST | 审计端点（路径修复，原 /api/action/audit） |

---

## 四、V6 核心改进详解

### 4.1 Writing Router 修复（P1-2）

**V5 问题**：`writing.py` 中的端点完全不能用：
- `continue_writing` 导入不存在的 `Pipeline` 类（应该是 `WritingPipeline`）
- 构造参数全错（传了 `llm, book_id, PROJECT_ROOT`，实际需要 20+ 个组件）
- `action_revise` 路由前缀重复（`/api/books/api/action/revise`）
- `three_layer_audit` 调用参数不匹配

**V6 修复**：
- 提取 `_build_pipeline(s)` 公共函数，正确构造完整的 WritingPipeline
- 统一路由路径：`/{book_id}/write`、`/{book_id}/revise`、`/{book_id}/audit`
- 正确传参给 `auditor.audit_chapter(content, chapter, blueprint, truth_ctx, settlement)`

### 4.2 自适应审查增强（P1-3）

**V5 adaptive 模式**：只检查 `chapter % interval == 0`（每N章强制全量）

**V6 增强**：新增两种触发条件：
1. **低分触发**：最近 3 章任一审计分 < `PIPELINE_REVIEW_FORCE_SCORE`（默认70）→ 全量
2. **连续返工触发**：最近 2 章都需要修订（revision_rounds > 0）→ 全量

```python
# _recent_low_score_trigger() 实现
# 读取 agent_performance.json → 检查最近3章的 audit_weighted_total
# 低于阈值 或 连续返工 → 返回 True → 全量审查
```

### 4.3 MiroFish 闭环（P2-4）

**V5**：MiroFish 测试结果保存到 `mirofish_report_chN.json`，但下一章完全不看

**V6**：在 `pipeline.run()` 开始时，加载最近一次 MiroFish 报告，将 `routed_tasks` 注入建筑师的 `world_context`：

```
最近读者测试（第15章，总分72/100）：
- core读者评分：65/100
- normal读者评分：75/100
读者反馈的改进方向：
- [high] → writer：对话过于直白，缺少潜台词
- [medium] → scene_architect：场景转换生硬
```

建筑师据此调整规划，写手据此注意读者痛点。

### 4.4 Token 追踪（P2-5）

`core/token_tracker.py`：
- `TrackedProvider` 包装器：每次 LLM 调用自动记录 agent/model/input/output tokens
- 按章节聚合：`get_chapter_usage(chapter)` → 该章消耗的总tokens和费用
- 费用估算：内置各模型定价（DeepSeek/Claude/GPT-4），自动算美元
- API 端点：`GET /api/books/{id}/token-usage` → JSON 报告

### 4.5 KB 热加载（P2-6）

**V5**：KB 内容在模块 import 时读取，修改文件要重启服务

**V6**：
- `_LazyKB` 代理：访问时才读取，自动检测文件修改时间
- `reload_all_kb()`：强制重新加载所有 KB 文件
- `check_kb_updates()`：检测哪些文件有更新（不加载）
- API 端点：
  - `POST /api/books/reload-kb` → 立即生效
  - `GET /api/books/kb-status` → 查看更新状态

### 4.6 错误恢复（P2-7）

Pipeline Checkpoint 机制：
1. 每章写前保存 checkpoint：`pipeline_checkpoint.json`
2. 写完后更新 completed_count
3. 中断时保存 `status: "interrupted"` + `failed_chapter` + `error`
4. `POST /api/books/{id}/resume` → 从上次中断处继续

---

## 五、技术栈

| 组件 | 技术 |
|------|------|
| 语言 | Python 3.11+ |
| 后端 | FastAPI |
| CLI | Typer |
| 数据存储 | 文件系统（JSON + Markdown） |
| LLM | DeepSeek API（默认）/ Ollama（本地免费）/ Claude / GPT-4 |
| 前端 | 单文件 HTML（暗色主题） |
| 校验 | Pydantic v2 |

---

## 六、文件结构（V6）

```
dramatica-flow-enhanced-v6/
├── cli/main.py                          # CLI入口
├── core/
│   ├── agents/                          # Agent模块
│   │   ├── __init__.py                  # re-export入口
│   │   ├── kb.py                        # 公共知识库模块（V6：热加载）
│   │   ├── architect.py                 # 建筑师
│   │   ├── writer.py                    # 写手
│   │   ├── auditor.py                   # 审计员
│   │   ├── reviser.py                   # 修订者
│   │   ├── summary.py                   # 摘要
│   │   ├── patrol.py                    # 巡查
│   │   ├── worldbuilder.py              # 世界观构建
│   │   ├── outline_planner.py           # 大纲规划
│   │   ├── market_analyzer.py           # 市场分析
│   │   └── enhanced/                    # 增强Agent
│   │       ├── character_growth.py
│   │       ├── dialogue.py
│   │       ├── emotion_curve.py
│   │       ├── feedback.py
│   │       ├── style_checker.py
│   │       ├── scene_architect.py
│   │       ├── psychological.py
│   │       ├── mirofish.py
│   │       └── methods.py
│   ├── pipeline.py                      # 写作管线（V6：自适应审查+MiroFish闭环）
│   ├── llm/__init__.py                  # LLM抽象层（V6：TrackedProvider）
│   ├── token_tracker.py                 # Token追踪（V6新增）
│   ├── narrative/__init__.py            # 叙事引擎
│   ├── state/__init__.py                # 状态管理
│   ├── types/                           # 数据类型
│   ├── validators/__init__.py           # 写后验证器
│   ├── server/                          # Web服务
│   │   ├── __init__.py                  # app实例+中间件+CORS+WebSocket
│   │   ├── deps.py                      # 公共依赖+请求模型
│   │   └── routers/                     # 路由模块
│   │       ├── books.py
│   │       ├── setup.py
│   │       ├── chapters.py
│   │       ├── outline.py
│   │       ├── writing.py               # V6：完全重写
│   │       ├── ai_actions.py
│   │       ├── threads.py
│   │       ├── analysis.py
│   │       ├── enhanced.py              # V6：新增token/kb端点
│   │       ├── settings.py
│   │       └── export.py
│   ├── quality_dashboard.py
│   ├── dynamic_planner.py
│   ├── kb_incentive.py
│   └── knowledge_base/                  # 知识库
├── templates/
├── tests/
├── docs/
├── dramatica_flow_web_ui.html
├── dramatica_flow_timeline.html
├── pyproject.toml
├── .env.example
├── PROJECT_HANDOFF.md                   # 本文件
└── USER_MANUAL.md
```

---

## 七、小白操作手册

### 7.1 首次部署（5步）

```bash
# 第1步：克隆项目
git clone https://github.com/ZTNIAN/dramatica-flow-enhanced-v6.git
cd dramatica-flow-enhanced-v6

# 第2步：创建虚拟环境
python3 -m venv .venv
source .venv/bin/activate

# 第3步：安装依赖
pip install -e .

# 第4步：配置API Key
cp .env.example .env
# 编辑 .env，填入 DeepSeek API Key

# 第5步：启动
# CLI: df --help
# Web: uvicorn core.server:app --reload --host 0.0.0.0 --port 8766
```

### 7.2 V6 新功能使用

**查看 Token 费用**：
```
GET /api/books/{book_id}/token-usage
```
返回每章每Agent的token消耗和美元费用估算。

**热加载知识库**：
修改 `core/knowledge_base/` 下的任何 .md 文件后：
```
POST /api/books/reload-kb
```
立即生效，无需重启。

**中断恢复**：
写作中断后（API 报错/网络断开等），checkpoint 自动保存：
```
GET  /api/books/{book_id}/checkpoint    # 查看状态
POST /api/books/{book_id}/resume        # 从断点继续
```

### 7.3 迭代方法

每次迭代只需要：
1. 把本文件 `PROJECT_HANDOFF.md` 发给 AI
2. 给 GitHub Token
3. AI 改代码 → 用 GitHub Contents API 推送
4. 你 revoke token

---

## 八、踩坑记录

（继承 V5 全部踩坑记录，新增以下）

### 坑13：writing router 的 Pipeline 构造

V5 的 `writing.py` 导入了不存在的 `Pipeline` 类。正确的类是 `WritingPipeline`，需要 20+ 个组件参数。解决方案是提取 `_build_pipeline()` 公共函数，与 CLI 的 `write` 命令使用相同逻辑。

### 坑14：FastAPI 路由模板语法

FastAPI 路由路径用 `{book_id}`，不是 `{{book_id}}`。双花括号是 Jinja2 模板语法，会导致 404。

### 坑15：KB 模块级变量与热加载冲突

V5 的 `KB_ANTI_AI = _load_kb(...)` 在 import 时读取，后续修改文件不会更新。V6 用 `_LazyKB` 代理解决：访问时才读，且检测文件修改时间。

---

## 九、迭代写入方式

推荐使用 GitHub Contents API 逐文件上传（git push 有 TLS 问题）。

```python
import base64, json, urllib.request, time
from urllib.parse import quote

TOKEN = "你的GitHub Token"
REPO = "ZTNIAN/dramatica-flow-enhanced-v6"

def upload(filepath, content, message):
    encoded = "/".join(quote(seg, safe="") for seg in filepath.split("/"))
    content_b64 = base64.b64encode(content.encode("utf-8")).decode()
    sha = ""
    try:
        url = f"https://api.github.com/repos/{REPO}/contents/{encoded}"
        req = urllib.request.Request(url, headers={
            "Authorization": f"token {TOKEN}", "Accept": "application/vnd.github+json"
        })
        sha = json.loads(urllib.request.urlopen(req, timeout=10).read()).get("sha", "")
    except: pass
    data = json.dumps({
        "message": message, "content": content_b64, "branch": "main",
        **({"sha": sha} if sha else {}),
    }).encode()
    req = urllib.request.Request(
        f"https://api.github.com/repos/{REPO}/contents/{encoded}",
        data=data, method="PUT",
        headers={
            "Authorization": f"token {TOKEN}",
            "Accept": "application/vnd.github+json",
            "Content-Type": "application/json",
        },
    )
    result = json.loads(urllib.request.urlopen(req, timeout=20).read())
    commit = result.get("commit", {}).get("sha", "ERROR")[:8]
    print(f"  ✅ {filepath} → {commit}")
    time.sleep(1.5)
```

---

*本文档由AI自动生成。下次迭代时，把本文件发给AI即可快速理解整个项目。*
