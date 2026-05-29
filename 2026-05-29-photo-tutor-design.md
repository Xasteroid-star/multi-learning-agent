# 拍照搜题 + 个性化引导 设计文档

> 日期：2026-05-29 | 状态：设计中 | 基于：multi-agent-education Python 版

## 1. 概述

在现有 5-Agent Mesh 基础上新增**拍照搜题+个性化引导**功能。学生上传数学题照片，OCR 识别题目后，系统通过 Agent 协作进行苏格拉底式引导教学，而非直接给答案。

### 1.1 核心设计决策

| 决策 | 选择 |
|---|---|
| 引导方式 | 系统主动引导，逐层追问（苏格拉底式） |
| 答案策略 | 条件触发揭示：Hint Level 3 后学生再错 2 次才展示完整答案 |
| 实现范围 | Python/FastAPI 后端 + React/TypeScript 前端 |
| 架构方式 | 新增 PhotoTutorAgent 作为第 6 个 Agent，通过 EventBus 协作 |
| LLM | 复用现有 MiniMax/OpenAI Vision API |

---

## 2. 架构设计

### 2.1 新增模块概览

```
python/
├── core/
│   ├── ocr_engine.py           ← 新增：Vision LLM 图片→题目文本
│   ├── problem_analyzer.py     ← 新增：题目→知识点+解答+引导问题
│   └── student_profile.py      ← 新增：学生画像存储
├── agents/
│   └── photo_tutor_agent.py    ← 新增：第6个Agent，管理拍照引导会话
├── api/
│   ├── routes.py               ← 修改：新增3个REST端点
│   ├── websocket.py            ← 修改：新增photo动作
│   └── orchestrator.py         ← 修改：注册PhotoTutorAgent
├── core/
│   └── event_bus.py            ← 修改：EventType枚举新增8个事件类型
└── tests/
    ├── test_ocr_engine.py      ← 新增
    ├── test_problem_analyzer.py ← 新增
    ├── test_photo_tutor.py     ← 新增
    ├── test_photo_integration.py ← 新增
    └── test_photo_routes.py    ← 新增
```

### 2.2 Agent 协作架构

```
POST /api/v1/photo-solve (multipart: 图片)
         │
         v
   PhotoSessionManager          ← 新建，管理会话状态
         │
         v
   ocr_engine.py               ← Vision LLM识别题目
         │
         v
   problem_analyzer.py         ← 提取知识点+难度+解答步骤+引导问题
         │
         v
   ┌─────────────────────────────────────────────┐
   │              EventBus                        │
   │                                              │
   │  PHOTO_SESSION_STARTED ──────────────────┐   │
   │  PROBLEM_RECOGNIZED  ──────┐             │   │
   │  GUIDANCE_QUESTION    ←────┼──────────┐  │   │
   │  STUDENT_PHOTO_REPLY  ──┐  │          │  │   │
   │  REPLY_JUDGED         ──┼──┼──────────┼──│   │
   │  STEP_COMPLETED       ──┼──┼──────────┼──│   │
   │  SOLUTION_REVEALED    ──┼──┼──────────┼──│   │
   │  PHOTO_SESSION_ENDED  ──┼──┼──────────┼──│   │
   └──────────────────────────│──│──────────│───┘   │
                              │  │          │       │
    ┌──────┬──────┬──────┬────┼──┼──────────┼───┐   │
    │      │      │      │    │  │          │   │   │
    v      v      v      v    v  v          v   v   │
  Assess Tutor Curric Engage PhotoTutor    Hint    │
  -ment                        (新Agent)           │
```

### 2.3 Agent 职责表

| Agent | 在拍照会话中的角色 |
|---|---|
| **PhotoTutorAgent**（新） | 会话状态机 + 引导对话编排 + 回复评判 |
| AssessmentAgent | 查询知识点掌握度；会话结束时更新 BKT |
| TutorAgent | 辅助生成苏格拉底式引导语（复用 `SOCRATIC_PROMPTS`） |
| HintAgent | 被 PhotoTutorAgent 请求时提供渐进提示 |
| EngagementAgent | 监听学生行为，检测挫败/疲劳 |
| CurriculumAgent | 会话结束后安排 SM-2 复习计划 |

---

## 3. 学生画像（Student Profile）

新增 `core/student_profile.py`，与现有 `LearnerModel`（BKT）互补：

```
┌──────────────────────┐       ┌──────────────────────┐
│   StudentProfile      │       │   LearnerModel (BKT)  │
│   - name, grade       │       │   - per-knowledge-pt  │
│   - learning_style    │  配   │   - mastery prob      │
│   - total_sessions    │  合   │   - attempts/streaks  │
│   - weak_topics[]     │  使   │   - alpha/beta        │
│   - strong_topics[]   │  用   │                       │
│   - recent_activity[] │       │                       │
│   - preferred_pace    │       │                       │
└──────────────────────┘       └──────────────────────┘
```

**Profile 在拍照流程中的使用：**

| 阶段 | 使用方式 |
|---|---|
| 分析题目 | 根据 `grade` 校准难度；从 `weak_topics` 预判卡点 |
| 生成引导 | 根据 `learning_style` 调整引导风格（视觉型/文字型） |
| 选优先级 | 若题目涉及多知识点，优先引导 `weak_topics` 中交叉的 |
| 会话结束 | 更新计数，刷新 `weak_topics`/`strong_topics` |

**存储：** SQLite 持久化，Agent 层内存缓存。API：`GET /api/v1/profile/{learner_id}`。

**Profile 字段：**

```python
class StudentProfile:
    learner_id: str              # 唯一标识
    name: str                    # 学生姓名
    grade: str                   # "初一" ~ "高三"
    learning_style: str          # "visual" | "textual" | "mixed"
    preferred_pace: str          # "fast" | "normal" | "slow"
    total_sessions: int          # 总学习次数
    total_photo_solves: int      # 拍照搜题次数
    weak_topics: list[str]       # 从BKT汇总的弱项知识点ID
    strong_topics: list[str]     # 掌握较好的知识点ID
    recent_activity: list[dict]  # 最近20条活动记录
    created_at: str
    updated_at: str
```

---

## 4. PhotoTutorAgent 状态机

### 4.1 状态转换图

```
                    ┌──────────┐

                    │   IDLE   │
                    └────┬─────┘
                         │ PHOTO_SESSION_STARTED
                    ┌────v──────┐
                    │ ANALYZING │ ← OCR + 知识点分析
                    └────┬──────┘
                         │ 分析完成
                    ┌────v──────┐
                    │  GUIDING  │ ← 发引导问题，等学生回复
                    └──┬──┬──┬──┘
                       │  │  │
           回复正确    │  │  │  回复不完整/部分正确
                       │  │  │
              ┌────────v──┐ │  ┌──────────────┐
              │  PRAISING │ │  │  FOLLOW_UP   │ ← 追问深挖
              └────┬──────┘ │  └──────┬───────┘
                   │        │         │
                   │   ┌────v──┐      │
                   │   │       │      │
                   │   │ HINTING├──┐   │
                   │   │(3级递进)│  │  │
                   │   └───┬────┘  │  │
                   │       │       │  │
                   │   学生答出    │ 学生仍卡住
                   │       │       │  │
                   v       v       v  v
              ┌─────────────────────────┐
              │   REVEALING              │ ← 展示完整答案
              │   条件：Level3后+2次失败  │
              └───────────┬─────────────┘
                          │
                   ┌──────v──────┐
                   │ SUMMARIZING │ ← 总结+更新BKT+安排复习
                   └──────┬──────┘
                          │
                    ┌─────v─────┐
                    │   CLOSED  │
                    └───────────┘
```

### 4.2 状态转移条件

| 当前状态 | 目标状态 | 触发条件 | 行为 |
|---|---|---|---|
| IDLE | ANALYZING | 前端上传图片 | 调用 OCR + ProblemAnalyzer |
| ANALYZING | GUIDING | 分析完成 | 发第一个苏格拉底引导题 |
| GUIDING | PRAISING | 学生答对核心步骤 | 肯定 → 推进到下一步 |
| GUIDING | FOLLOW_UP | 答案模糊/不完整 | "你从哪一步开始想的？" |
| GUIDING | HINTING | 连续2次回复没进展 | 请求 HintAgent |
| HINTING | GUIDING | 提示后学生有新回复 | 回到引导继续 |
| HINTING | REVEALING | Level 3 + 再错2次 | 展示完整答案 |
| PRAISING | GUIDING | 还有未完成的子步骤 | 继续引导下个步骤 |
| PRAISING | SUMMARIZING | 所有步骤完成 | 总结回顾 |
| REVEALING | SUMMARIZING | 答案展示完毕 | 总结+标记弱项 |
| SUMMARIZING | CLOSED | 总结完成 | 清理会话 |

### 4.3 会话生命周期

- **超时：** 30 分钟无交互 → 自动 SUMMARIZING → CLOSED
- **清理：** CLOSED 后 1 小时 → 从 PhotoSessionManager 移除
- **并发限制：** 每 learner_id 最多 3 个活跃会话

---

## 5. OCR Engine + Problem Analyzer

### 5.1 ocr_engine.py

被 PhotoTutorAgent 在 ANALYZING 阶段直接调用，不参与 Agent Mesh。

```python
async def recognize_math_from_photo(image_bytes: bytes) -> OCRResult:
    """调用 Vision LLM 识别数学题目"""

class OCRResult:
    problem_text: str          # "已知二次函数 f(x)=x²+2x-3，求其顶点坐标"
    has_math_formula: bool     # 是否包含数学公式
    confidence: float          # 识别置信度 (0-1)
    raw_llm_response: str      # 原始LLM返回（调试用）
```

用 Vision LLM（MiniMax/OpenAI 多模态接口）而不用传统 OCR，因数学公式包含 `x²`、`√`、`∑` 等特殊符号。

### 5.2 problem_analyzer.py

被 PhotoTutorAgent 在 ANALYZING 阶段调用。

```python
async def analyze_problem(
    problem_text: str,
    student_profile: StudentProfile
) -> ProblemAnalysis:

class ProblemAnalysis:
    problem_text: str
    knowledge_points: list[str]     # ["二次函数顶点式", "配方法"]
    difficulty: int                 # 1-5
    solution_steps: list[SolutionStep]  # 完整答案（暂不展示给学生）
    relevance_to_weak: float        # 与弱项的关联度

class SolutionStep:
    step_number: int
    description: str            # "将一般式化为顶点式"
    key_insight: str            # "配方法的关键是把一次项系数除2再平方"
    socratic_prompt: str        # "你能把 x²+2x-3 写成完全平方形式吗？"
```

- `solution_steps` 是完整答案，服务端持有，**只在触发揭示条件时发给学生**
- `socratic_prompts` 按步骤拆分，一次只问一步

---

## 6. 新增 EventType 与 Agent 订阅关系

### 6.1 新增 8 个事件类型

在 `core/event_bus.py` 的 `EventType` 枚举中新增：

| EventType | 含义 | 携带数据 |
|---|---|---|
| `PHOTO_SESSION_STARTED` | 拍照会话启动 | session_id, image_bytes_size |
| `PROBLEM_RECOGNIZED` | OCR+分析完成 | session_id, knowledge_points, difficulty |
| `GUIDANCE_QUESTION` | 发送引导问题 | session_id, step_number, question_text |
| `STUDENT_PHOTO_REPLY` | 学生回复引导 | session_id, reply_text, step_number |
| `REPLY_JUDGED` | 回复评判完成 | session_id, judgement(correct/partial/wrong), step_number |
| `STEP_COMPLETED` | 一个解题步骤完成 | session_id, step_number, attempts_used |
| `SOLUTION_REVEALED` | 答案已揭示 | session_id, solution_steps, weak_points_marked |
| `PHOTO_SESSION_ENDED` | 会话结束 | session_id, total_steps, total_attempts, outcome |

### 6.2 Agent 订阅关系

| EventType | PhotoTutor | Assessment | Tutor | Hint | Curriculum | Engagement |
|---|---|---|---|---|---|---|
| STUDENT_SUBMISSION | | ✓ | | | | ✓ |
| PHOTO_SESSION_STARTED | ✓ | ✓(查询) | ✓(辅助) | | | |
| PROBLEM_RECOGNIZED | ✓ | | | | | |
| GUIDANCE_QUESTION | ✓ | | | | | ✓(监听) |
| STUDENT_PHOTO_REPLY | ✓ | | | | | ✓ |
| REPLY_JUDGED | ✓ | ✓(记录) | | ✓(触发) | | |
| STEP_COMPLETED | ✓ | | | | ✓(检查) | ✓ |
| SOLUTION_REVEALED | ✓ | ✓(标记弱项) | | | ✓(安排复习) | |
| PHOTO_SESSION_ENDED | ✓ | ✓(更新BKT) | | | ✓(SM-2) | ✓(清理) |

---

## 7. API 端点

### 7.1 新增 REST 端点

**POST /api/v1/photo-solve**
```
Content-Type: multipart/form-data
参数: image (file), learner_id (str)
返回 200: {
  "session_id": "ps_abc123",
  "problem_text": "已知二次函数...",
  "knowledge_points": ["二次函数", "配方法"],
  "first_guidance": "你能识别出这道题是哪种函数类型吗？"
}
错误: 400 (非图片), 413 (过大), 422 (无法识别)
```

**POST /api/v1/photo-session/{session_id}/reply**
```
Body: { "learner_id": "u1", "reply": "这是二次函数..." }
返回 200: {
  "action": "follow_up" | "praise" | "hint" | "reveal" | "summarize",
  "message": "对！那你知道怎么求顶点坐标吗？",
  "hint_level": null | 1 | 2 | 3,
  "session_state": "GUIDING"
}
```

**GET /api/v1/photo-session/{session_id}**
```
返回 200: 当前会话完整状态（断线重连用）
包括: problem_text, conversation_history, current_step, hint_count, state
```

**GET /api/v1/profile/{learner_id}**
```
返回 200: StudentProfile + BKT mastery summary
```

### 7.2 WebSocket 新增动作

```json
// 客户端 → 服务端
{ "action": "photo_reply", "session_id": "ps_abc", "reply": "..." }

// 服务端 → 客户端（除现有事件外新增）
{ "type": "photo_guidance", "data": { "question": "...", "step": 1 } }
{ "type": "photo_hint", "data": { "level": 2, "hint": "..." } }
{ "type": "photo_reveal", "data": { "steps": [...] } }
```

---

## 8. 前端设计

### 8.1 布局

```
┌──────────────────────────────────────────────────┐
│  🔵 已连接   学生: 小明 (初三)    题库: 200+      │
├────────────────────┬─────────────────────────────┤
│                    │                             │
│   📷 拍照搜题      │   事件流                     │
│                    │                             │
│  ┌──────────────┐  │  ┌─ PhotoTutorAgent ──────┐│
│  │   图片预览    │  │  │ 💬 请观察这个二次函数.. ││
│  │  (点击上传)   │  │  └────────────────────────┘│
│  └──────────────┘  │                             │
│                    │  ┌─ 👤 你 ─────────────────┐│
│  📸拍照 [📎]上传   │  │ 这是二次函数，标准形式    ││
│                    │  └────────────────────────┘│
│  ┌─ 对话区 ──────┐ │                             │
│  │ 💬 系统: ...  │ │  ┌─ HintAgent ────────────┐│
│  │ 👤 你: ...    │ │  │ 💡 L1提示：回忆配方法    ││
│  │ 💡 L2: ...    │ │  └────────────────────────┘│
│  │ 📝 完整答案   │ │                             │
│  │ [输入框][发送]│ │                             │
│  └──────────────┘  │                             │
├────────────────────┴─────────────────────────────┤
│  📊 知识图谱 | 📝 错题本 | 🎯 复习计划           │
└──────────────────────────────────────────────────┘
```

### 8.2 组件结构

```
App.tsx
├── Header (已有)
├── LeftPanel
│   ├── PhotoUpload           ← 新建：图片上传+预览
│   └── PhotoChat             ← 新建：引导对话界面
│       ├── ChatMessage       ← 对话气泡
│       ├── HintBanner        ← 提示横幅 (L1/L2/L3)
│       └── SolutionReveal    ← 答案揭示卡片
├── RightPanel
│   └── EventStream (已有)    ← 实时Agent事件
└── Footer (已有)
```

### 8.3 对话消息类型

```typescript
type ChatMessage =
  | { role: "system"; text: string; type: "guidance" }
  | { role: "student"; text: string }
  | { role: "system"; text: string; type: "hint"; level: 1 | 2 | 3 }
  | { role: "system"; text: string; type: "praise" }
  | { role: "system"; text: string; type: "follow_up" }
  | { role: "system"; steps: SolutionStep[]; type: "reveal" }
  | { role: "system"; text: string; type: "summary" }
```

---

## 9. 错误处理

| 阶段 | 错误场景 | 处理方式 |
|---|---|---|
| 上传 | 图片 >10MB | 前端限制 + 后端 413 |
| 上传 | 非图片格式 | 校验 MIME type |
| OCR | 模糊/无法识别 | confidence<0.5 提示重拍 |
| OCR | 非数学内容 | LLM返回NOT_MATH，提示重传 |
| OCR | API超时/限流 | 重试1次→提示稍后再试 |
| 分析 | 知识点不在图谱 | 降级为文本标签，不阻断流程 |
| 引导 | 学生输入无关回复 | 礼貌引导回正题 |
| 引导 | 会话过期(>30min) | 自动关闭，提示重新开始 |
| 引导 | 断线重连 | WS重连后GET会话恢复 |
| 揭示 | 无缓存答案 | 兜底重新调用analyze |
| 通用 | Agent异常 | `_safe_handle`捕获，不拖垮EventBus |

---

## 10. 测试策略

```
tests/
├── test_ocr_engine.py          ← 新增
│   ├── test_recognize_clear_math_photo
│   ├── test_recognize_blurry_returns_low_confidence
│   ├── test_recognize_non_math_returns_not_math
│   └── test_recognize_api_timeout_retry
│
├── test_problem_analyzer.py    ← 新增
│   ├── test_analyze_quadratic_problem
│   ├── test_extract_knowledge_points
│   ├── test_solution_steps_ordered
│   └── test_weak_topics_prioritized
│
├── test_photo_tutor_agent.py   ← 新增
│   ├── test_state_idle_to_analyzing
│   ├── test_state_guiding_to_praising
│   ├── test_state_guiding_to_hinting
│   ├── test_state_hinting_level3_twice_to_revealing
│   ├── test_state_revealing_to_summarizing
│   ├── test_reply_judged_correct
│   ├── test_reply_judged_partial_triggers_follow_up
│   ├── test_reply_judged_wrong_increments_attempts
│   └── test_session_timeout_to_closed
│
├── test_photo_integration.py   ← 新增
│   ├── test_full_flow_upload_to_guided_solve
│   ├── test_full_flow_max_hints_then_reveal
│   ├── test_bkt_updated_on_session_end
│   └── test_weak_points_marked_after_reveal
│
├── test_photo_routes.py        ← 新增
│   ├── test_post_photo_solve_returns_session
│   ├── test_post_reply_returns_next_action
│   └── test_get_session_restores_state
│
└── test_agents.py              ← 已有，确保不被破坏
```
