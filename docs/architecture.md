# 架构设计详解

## 1. 整体架构

本系统采用 **Mesh + 事件驱动** 架构，6 个 Agent 通过 EventBus 双向异步通信。

```
                          ┌──────────────┐
                          │  React 前端   │
                          │  demo.html   │
                          │  (WebSocket  │
                          │   + REST)    │
                          └──────┬───────┘
                                 │
                          ┌──────▼───────┐
                          │  API Gateway │
                          │  FastAPI     │
                          └──────┬───────┘
                                 │
                    ┌────────────▼────────────┐
                    │     EventBus (24事件)    │
                    │  pub/sub · asyncio.gather │
                    └────┬───┬───┬───┬───┬────┘
                         │   │   │   │   │
       ┌─────────────────┘   │   │   │   └─────────────────┐
       │                     │   │   │                     │
  ┌────▼─────┐  ┌──────────┐ │ ┌─▼───▼──┐  ┌──────────┐ ┌▼──────────┐
  │ Photo   │  │Assessment│ │ │ Tutor  │  │Curriculum│ │Engagement │
  │ Tutor   │◄─┤  Agent   │◄┼─┤ Agent  ├─►│  Agent   │─►│  Agent    │
  │ Agent   │  │ (BKT)    │ │ │(苏格拉底)│  │ (SM-2)   │ │(状态监测) │
  └────┬────┘  └────┬─────┘ │ └───┬─────┘  └────┬─────┘ └─────┬─────┘
       │            │       │     │              │             │
       │       ┌────▼───┐   │     │              │             │
       └──────►│ Hint   │◄──┘     │              │             │
               │ Agent  │         │              │             │
               │(3级提示)│         │              │             │
               └────────┘         │              │             │
                                  │              │             │
                          ┌───────┴──────────────┴─────────────┘
                          ▼
                  ┌───────────────┐
                  │ 共享学习者状态  │
                  │ LearnerModel  │
                  │ + ProfileStore│
                  └───────────────┘
```

## 2. 6 个 Agent 职责

| Agent | 职责 | 订阅事件 | 发布事件 |
|---|---|---|---|
| **PhotoTutorAgent** | 拍照会话状态机 + 引导编排 + 回复评判 | PHOTO_SESSION_STARTED, PROBLEM_RECOGNIZED, GUIDANCE_QUESTION, STUDENT_PHOTO_REPLY, REPLY_JUDGED, STEP_COMPLETED, SOLUTION_REVEALED, PHOTO_SESSION_ENDED | 同左（编排中转） |
| **AssessmentAgent** | BKT 掌握度评估 | STUDENT_SUBMISSION, STUDENT_QUESTION | MASTERY_UPDATED, WEAKNESS_DETECTED, ASSESSMENT_COMPLETE |
| **TutorAgent** | 苏格拉底式教学 | ASSESSMENT_COMPLETE, STUDENT_MESSAGE, HINT_RESPONSE, ENGAGEMENT_ALERT | TEACHING_RESPONSE, HINT_NEEDED, DIFFICULTY_ADJUSTED |
| **CurriculumAgent** | 学习路径 + SM-2 排期 | MASTERY_UPDATED, WEAKNESS_DETECTED, PACE_ADJUSTMENT | PATH_UPDATED, REVIEW_SCHEDULED, NEXT_TOPIC |
| **HintAgent** | 3 级渐进提示 | HINT_NEEDED | HINT_RESPONSE |
| **EngagementAgent** | 学习状态监测 | STUDENT_SUBMISSION, ASSESSMENT_COMPLETE, STUDENT_MESSAGE | ENGAGEMENT_ALERT, ENCOURAGEMENT, PACE_ADJUSTMENT |

## 3. 拍照引导完整事件流

```
POST /api/v1/photo-solve (上传图片)
        │
        ▼
  [ocr_engine] Vision LLM 识别题目
  [problem_analyzer] LLM 分析知识点 + 拆解题步骤 + 生成引导问题
        │
        ▼
  orchestrator.create_photo_session()
        │
        ▼
  ┌────────────────────────────────────────────────────────────┐
  │                    PhotoSession 状态机                      │
  │                                                            │
  │  IDLE → ANALYZING → GUIDING → PRAISING → SUMMARIZING → CLOSED
  │                   │   │        │                            │
  │                   │   ├→ FOLLOW_UP → GUIDING               │
  │                   │   └→ HINTING (L1→L2→L3)               │
  │                   │        │                                │
  │                   │        └→ REVEALING (L3 + 2次错)       │
  │                   │             │                           │
  │                   │             └→ SUMMARIZING             │
  └────────────────────────────────────────────────────────────┘
        │
        ▼
  POST /api/v1/photo-session/{id}/reply
        │
        ▼
  orchestrator.submit_photo_reply()
        │
        ├→ _judge_reply() → correct / partial / wrong
        ├→ 正确 → complete_current_step() → 还有下一步 → 继续引导
        │                                → 全部完成 → summarize
        ├→ 模糊 → follow_up 追问
        └→ 错误 → increment_attempts
                → hint_count < 3 → record_hint(L1/L2/L3)
                → hint_count >=3 && attempts >=2 → REVEAL 答案
```

### 提示→揭示边界逻辑

```
const HINT_LIMIT = 3        // 最多 3 级提示
const REVEAL_ATTEMPTS = 2   // 达到最高级别后再错 2 次才揭示

function handleWrongAnswer(session):
    session.attempts_since++

    if session.hint_count >= HINT_LIMIT and session.attempts_since >= REVEAL_ATTEMPTS:
        return REVEAL  // 展示完整答案

    level = min(session.hint_count + 1, HINT_LIMIT)
    session.hint_count++
    session.attempts_since = 0
    return HINT(level)  // L1/L2/L3 提示
```

## 4. 为什么选择 Mesh + 事件驱动

| 模式 | 特点 | 适合场景 |
|---|---|---|
| **Supervisor** | 中心调度，单点瓶颈 | 简单串行任务 |
| **Pipeline** | 线性流转，不灵活 | 数据处理 |
| **Mesh + EventBus** ✅ | Agent 自由通信，松耦合 | **教育场景：实时双向交互** |

**我们的选择理由：**

- PhotoTutor 引导时可能随时需要 HintAgent 提供提示
- Assessment 评估完需要通知 Curriculum 调整路径和 Engagement 分析状态
- Agent 间是**双向、异步、事件驱动**的，不是串行调用链
- 新增 Agent（如我们新增的 PhotoTutorAgent）只需订阅事件，不改现有代码 — **开闭原则**

## 5. 三种语言事件总线对比

| 维度 | Python | Java | Go |
|---|---|---|---|
| 事件总线 | 自定义 EventBus (asyncio) | Spring ApplicationEvent | channel + goroutine |
| 订阅 | `bus.subscribe(type, handler)` | `@EventListener` | `bus.Subscribe(type, fn)` |
| 并发 | `asyncio.gather` | `@Async` 线程池 | `go func()` |
| 线程安全 | asyncio 单线程 | ConcurrentHashMap | sync.RWMutex |
| 分发 | 并发通知所有 handler | Spring 容器管理 | 每 handler 独立 goroutine |

## 6. 数据模型

### 学习者状态

```
LearnerModel (BKT)
├── learner_id
├── knowledge_states: {
│     "二次函数": KnowledgeState {
│       mastery: 0.72,      // P(L) 掌握概率
│       alpha: 7.2,          // Beta 分布 α
│       beta: 2.8,           // Beta 分布 β
│       attempts: 10,
│       streak: 3,           // 连续正确次数
│       level: "proficient"  // NOT_STARTED → BEGINNER → DEVELOPING → PROFICIENT → MASTERED
│     }
│   }
└── bkt_params: { p_init: 0.1, p_transit: 0.15, p_guess: 0.2, p_slip: 0.1 }

StudentProfile (SQLite)
├── learner_id, name, grade
├── learning_style: "visual" | "textual" | "mixed"
├── weak_topics: ["配方法", "二次函数"]
├── strong_topics: ["有理数"]
└── total_sessions, total_photo_solves

PhotoSession (内存)
├── session_id, learner_id
├── state: SessionState (9 种状态)
├── problem_analysis: ProblemAnalysis
│   ├── knowledge_points, difficulty
│   └── solution_steps: [SolutionStep { socratic_prompt, key_insight }]
├── conversation_history: [ConversationEntry]
├── hint_count, attempts_since_last_hint
└── created_at, last_activity
```

### 状态一致性保证

- **单写者策略**：mastery 只有 AssessmentAgent 写入；hint 只有 HintAgent 管理；会话状态只有 PhotoTutorAgent 持有
- **事件溯源**：所有变更通过 Event 记录，EventBus 保留历史
- **故障隔离**：每个 handler 包裹 `try/catch`（Python）、`defer recover()`（Go），一个 Agent 崩溃不影响其他

## 7. 知识图谱 DAG

```
有理数 → 整式运算 → 一元一次方程 → 一元二次方程 → 函数 → 二次函数
                                     ↘ 因式分解 ↗        ↘ 三角函数
                                                        ↘ 解析几何
```

课程学习顺序用 Kahn 算法（BFS 拓扑排序）保证前置知识先学。

## 8. API 设计

```
REST (FastAPI)
├── POST /photo-solve          ← 拍照上传 (multipart)
├── POST /photo-session/{id}/reply  ← 引导回复
├── GET  /photo-session/{id}   ← 会话查询 (断线重连)
├── GET  /profile/{learner_id} ← 学生画像 + BKT
├── POST /submit               ← 答题提交
├── POST /question             ← 提问
├── POST /message              ← 消息
├── GET  /progress/{id}        ← 学习进度
└── GET  /knowledge-graph      ← 知识图谱

WebSocket
├── ws://host/ws/{learner_id}
└── actions: submit | question | message | photo_reply
```

## 9. 前端架构

```
demo.html (独立，无需构建)
├── 左面板
│   ├── 学生选择 (ID + 年级)
│   ├── 拍照/上传 (拖拽 + 点击)
│   ├── 知识点标签
│   └── 步骤进度条
├── 右面板
│   ├── 对话流 (导师提问 / 学生回答 / 提示 / 答案揭示)
│   └── 输入框 + 发送按钮
└── 直连 localhost:8000 API (fetch + FormData)
```
