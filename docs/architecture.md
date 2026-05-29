# 架构设计详解

## 1. 整体架构

本系统采用双层架构：**拍照引导流程**走 Orchestrator 直接调用（低延迟同步链路），**学习评估反馈**走 Mesh + EventBus 事件驱动（Agent 间双向异步通信）。

```
                        ┌──────────────────┐
                        │ Vanilla HTML 前端  │
                        │   demo.html       │
                        │   (REST fetch)    │
                        └────────┬──────────┘
                                 │
                        ┌────────▼──────────┐
                        │   API Gateway     │
                        │   FastAPI         │
                        └──┬───────────┬────┘
                           │           │
              ┌────────────▼──┐   ┌───▼──────────────┐
              │ Orchestrator  │   │  EventBus (24事件) │
              │ (拍照流同步调) │   │ pub/sub · async    │
              └──────┬────────┘   └──┬───┬───┬───┬────┘
                     │               │   │   │   │
                     ▼          ┌────┘   │   │   └────┐
              PhotoSession     │        │   │         │
              状态机 + 评判    │   ┌────▼───▼──┐  ┌───▼──────┐
                               │   │ Tutor    │  │Curriculum│
              ┌────────────────┘   │ Agent    │  │ Agent    │ ...
              │                    └────┬─────┘  └──────────┘
              ▼                         │
        ┌──────────┐              ┌─────▼─────┐
        │Assessment│              │  Hint     │
        │ Agent    │              │  Agent    │
        │ (BKT)    │              │ (3级提示)  │
        └────┬─────┘              └───────────┘
             │                         ▲
             │    ┌─────────────┐      │
             └───►│ Engagement  │──────┘
                  │ Agent       │
                  │ (状态监测)   │
                  └─────────────┘
                           │
                  ┌────────▼────────┐
                  │ 共享学习者状态    │
                  │ LearnerModel    │
                  │ + ProfileStore  │
                  └─────────────────┘
```

### 为什么拍照流走 Orchestrator 而不是 EventBus？

拍照引导是一个**同步请求-响应链路**：上传 → OCR → 分析 → 引导提问 → 学生回答 → 评判 → 下一问题。这条链路不需要并行处理，走 EventBus 反而增加复杂度。Orchestrator 直接调用 `create_photo_session()` 和 `submit_photo_reply()`，返回结果给前端。

而 5 个学习 Agent 的评估-教学-排期-提示-监测是高内聚的双向交互，走 EventBus 实现松耦合。

## 2. 6 个 Agent 职责

| Agent | 职责 | 通信方式 | 订阅事件 |
|---|---|---|---|
| **PhotoTutorAgent** | 管理 PhotoSessionManager + 回复评判 `_judge_reply()` | Orchestrator 直接调用 | PHOTO_SESSION_STARTED 等 8 个（预留，当前 pass） |
| **AssessmentAgent** | BKT 掌握度评估 | EventBus | STUDENT_SUBMISSION, STUDENT_QUESTION |
| **TutorAgent** | 苏格拉底式教学 | EventBus | ASSESSMENT_COMPLETE, STUDENT_MESSAGE, HINT_RESPONSE, ENGAGEMENT_ALERT |
| **CurriculumAgent** | 学习路径 + SM-2 排期 | EventBus | MASTERY_UPDATED, WEAKNESS_DETECTED, PACE_ADJUSTMENT |
| **HintAgent** | 3 级渐进提示 | EventBus | HINT_NEEDED |
| **EngagementAgent** | 学习状态监测 | EventBus | STUDENT_SUBMISSION, ASSESSMENT_COMPLETE, STUDENT_MESSAGE |

PhotoTutorAgent 订阅了 8 个拍照事件但当前 handler 都是 `pass` 占位 — 拍照引导的核心逻辑实现在 `orchestrator.py` 的 `create_photo_session()` 和 `submit_photo_reply()` 中。这为将来改为完全事件驱动预留了接口。

## 3. 事件流设计

### 核心事件流：学生答题（EventBus 驱动）

```
学生答题
  → STUDENT_SUBMISSION 事件
  → Assessment Agent → BKT 更新 mastery
      → MASTERY_UPDATED → Curriculum Agent（SM-2 复习排期）
      → ASSESSMENT_COMPLETE → Tutor Agent（苏格拉底回复）
                            → Engagement Agent（分析学习状态）
  → 如果检测到挫败 → ENGAGEMENT_ALERT
      → Tutor Agent（降低难度）
      → Curriculum Agent（放慢节奏）
```

### 拍照引导流（Orchestrator 同步调用）

```
POST /api/v1/photo-solve
  → ocr_engine.recognize_math_from_photo()  (Vision LLM)
  → problem_analyzer.analyze_problem()       (LLM 分析)
  → orchestrator.create_photo_session()      (初始化状态机)
  ← 返回 session_id + first_guidance

POST /api/v1/photo-session/{id}/reply
  → orchestrator.submit_photo_reply()
      → _judge_reply(correct/partial/wrong)
      → 正确 → complete_current_step → 继续 / 完成
      → 模糊 → follow_up 追问
      → 错误 → increment → hint(L1/L2/L3) / reveal
  ← 返回 { action, message, session_state }
```

### 提示流：学生卡住（EventBus 驱动）

```
学生连续答错
  → Tutor Agent 检测 attempts >= 2
  → HINT_NEEDED 事件
  → Hint Agent 判断级别 (1/2/3)
  → HINT_RESPONSE 事件
  → Tutor Agent 转发给学生
```

## 4. 拍照会话状态机

```
IDLE → ANALYZING → GUIDING ─┬→ PRAISING → SUMMARIZING → CLOSED
                             ├→ FOLLOW_UP → GUIDING
                             └→ HINTING (L1→L2→L3)
                                  │
                                  └→ REVEALING → SUMMARIZING → CLOSED
                                       ↑
                                  L3 + 2次错触发
```

### 提示→揭示边界逻辑

```
HINT_LIMIT = 3          # 最多 3 级提示
REVEAL_ATTEMPTS = 2     # L3 后连续 2 次错才揭示

function handleWrong(session):
    session.attempts_since_last_hint += 1

    if session.hint_count >= 3 and session.attempts_since_last_hint >= 2:
        return REVEAL  # 展示完整答案 → SUMMARIZING → CLOSED

    level = min(session.hint_count + 1, 3)
    session.record_hint(level)
    return HINT(level)
```

### 9 种会话状态

| 状态 | 含义 |
|---|---|
| IDLE | 等待开始 |
| ANALYZING | OCR + 知识点分析中 |
| GUIDING | 等待学生回答引导问题 |
| PRAISING | 表扬正确回答 |
| FOLLOW_UP | 追问模糊回答 |
| HINTING | 提供分级提示 |
| REVEALING | 揭示完整答案 |
| SUMMARIZING | 总结回顾 |
| CLOSED | 会话结束 |

## 5. 为什么选择 Mesh + 事件驱动

| 模式 | 特点 | 适合场景 |
|---|---|---|
| **Supervisor** | 中心调度，单点瓶颈 | 简单串行任务 |
| **Pipeline** | 线性流转，不灵活 | 数据处理 |
| **Mesh + EventBus** | Agent 自由通信，松耦合 | 教育场景：实时双向交互 |

**选择理由：**

- Assessment 评估完 → 同时通知 Curriculum（排期）和 Engagement（状态分析）—— 不是串行链
- Tutor 随时可能请求 HintAgent → 事件解耦
- 新增 Agent（如 PhotoTutorAgent）只需订阅事件，不改现有代码 —— **开闭原则**

## 6. 数据模型

```
LearnerModel (BKT, 内存)
├── learner_id
├── knowledge_states: dict[str, KnowledgeState]
│     ├── mastery: float         # P(L) 掌握概率
│     ├── alpha: float           # Beta 分布 α
│     ├── beta: float            # Beta 分布 β
│     ├── attempts: int
│     ├── correct_count: int
│     ├── streak: int            # 连续正确
│     ├── last_attempt: datetime
│     ├── level: MasteryLevel    # NOT_STARTED/BEGINNER/DEVELOPING/PROFICIENT/MASTERED
│     └── confidence: float      # 数据越多越准
├── bkt_params: BKTParams { p_init, p_transit, p_guess, p_slip }
├── session_start: datetime
├── total_interactions: int
└── metadata: dict

StudentProfile (SQLite, 持久化)
├── learner_id (PK), name, grade
├── learning_style: "visual" | "textual" | "mixed"
├── preferred_pace: "fast" | "normal" | "slow"
├── total_sessions, total_photo_solves
├── weak_topics: list[str]       # JSON column
├── strong_topics: list[str]     # JSON column
├── recent_activity: list[dict]  # JSON column
├── created_at, updated_at

PhotoSession (内存, 每次拍照会话)
├── session_id: "ps_" + uuid
├── learner_id
├── state: SessionState
├── problem_analysis: ProblemAnalysis
│     ├── problem_text
│     ├── knowledge_points: list[str]
│     ├── difficulty: int (1-5)
│     ├── solution_steps: list[SolutionStep]
│     │     ├── step_number
│     │     ├── description
│     │     ├── key_insight       # 关键词，用于评判回答
│     │     └── socratic_prompt   # 引导式提问
│     └── relevance_to_weak: float
├── current_step: int             # 当前第几步
├── conversation_history: list[ConversationEntry]
│     ├── role: "system" | "student"
│     ├── msg_type: "guidance"|"hint"|"praise"|"follow_up"|"reveal"|"summary"|"reply"
│     ├── hint_level: int | None
│     └── timestamp
├── hint_count, attempts_since_last_hint
├── created_at, last_activity

PhotoSessionManager (内存)
├── _sessions: dict[str, PhotoSession]
├── create_session(learner_id, analysis) → PhotoSession
├── get_session(session_id) → PhotoSession | None
├── close_session(session_id)
├── count_active(learner_id) → int
├── cleanup_expired() → 清理 >30min 会话
└── 限制：每 learner 最多 3 个活跃会话
```

### 状态一致性

- **单写者策略**：mastery 只有 AssessmentAgent 写入，提示级别只有 HintAgent 决定，会话状态只有 PhotoTutorAgent 持有
- **事件溯源**：EventBus 保留事件历史，可追溯状态变更
- **故障隔离**：每个 handler 包裹 try/catch，一个 Agent 异常不影响其他

## 7. 知识图谱

20 个节点的 DAG，用 Kahn 算法（BFS 拓扑排序）保证前置知识先学：

```
算术运算 → 分数运算 → 负数 → 代数式
    → 一元一次方程 → 二元一次方程组 → 不等式
    → 因式分解 → 一元二次方程 → 二次函数
    → 平面直角坐标系 → 一次函数 → 反比例函数
    → 勾股定理 → 相似三角形 → 锐角三角函数
    → 概率初步 → 数据统计 → 数列 → 集合 → 简易逻辑
```

代码：`core/knowledge_graph.py` → `build_sample_math_graph()`

## 8. 配置

```
config/settings.py (pydantic-settings, 从 .env 加载)
├── openai_api_key, openai_model, openai_base_url
├── minimax_api_key, minimax_model
├── database_url, redis_url
├── api_port, log_level
```

LLM 调用优先级：`OPENAI_API_KEY` 未配置时用 `MINIMAX_API_KEY`，均未配置走 mock fallback。

## 9. API 设计

```
REST (FastAPI)
├── GET  /health                  ← 健康检查
├── POST /photo-solve             ← 拍照上传 (multipart)
├── POST /photo-session/{id}/reply ← 引导回复
├── GET  /photo-session/{id}      ← 会话查询 (断线重连)
├── GET  /profile/{learner_id}    ← 学生画像 + BKT
├── POST /submit                  ← 答题提交
├── POST /question                ← 提问
├── POST /message                 ← 消息
├── GET  /progress/{id}           ← 学习进度
└── GET  /knowledge-graph         ← 知识图谱

WebSocket (备用)
├── ws://host/ws/{learner_id}
└── actions: submit | question | message | photo_reply
```

## 10. 前端架构

`demo.html` — 单个 Vanilla HTML 文件，无需构建，浏览器直接打开。

```
demo.html
├── 左面板
│   ├── 学生选择 (ID + 年级)
│   ├── 拍照/上传 (点击选择文件)
│   ├── 知识点标签
│   └── 步骤进度条
├── 右面板
│   ├── 对话流 (导师提问 / 学生回答 / 提示 / 答案揭示)
│   └── 输入框 + 发送按钮
└── 通信：fetch() → REST API (localhost:8000)
```

## 11. 目录结构

```
python/
├── agents/                     # 6 个 Agent
│   ├── photo_tutor_agent.py    # 拍照引导 (session_manager + _judge_reply)
│   ├── assessment_agent.py     # BKT 评估
│   ├── tutor_agent.py          # 苏格拉底教学
│   ├── curriculum_agent.py     # SM-2 排期
│   ├── hint_agent.py           # 3 级提示
│   ├── engagement_agent.py     # 状态监测
│   └── base_agent.py           # Agent 基类
├── core/
│   ├── event_bus.py            # EventBus + 24 EventType
│   ├── learner_model.py        # BKT + KnowledgeState
│   ├── spaced_repetition.py    # SM-2
│   ├── knowledge_graph.py      # 20 节点 DAG
│   ├── ocr_engine.py           # Vision LLM → OCRResult
│   ├── problem_analyzer.py     # LLM → ProblemAnalysis + SolutionStep
│   ├── photo_session.py        # PhotoSession + PhotoSessionManager
│   └── student_profile.py      # StudentProfile + ProfileStore
├── api/
│   ├── main.py                 # FastAPI + lifespan
│   ├── orchestrator.py         # Agent 编排 + 拍照流方法
│   ├── routes.py               # 10 个 REST 端点
│   └── websocket.py            # WebSocket (submit/question/message/photo_reply)
├── config/
│   └── settings.py             # pydantic-settings (.env)
└── tests/                      # 65 个测试
```
