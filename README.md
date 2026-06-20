# MathGuide — 拍照搜题 · 个性化引导 · 6-Agent Mesh

> 拍照上传数学题 → AI 不直接给答案，用苏格拉底式提问一步步引导你思考

[![Python](https://img.shields.io/badge/Python-3.12+-blue.svg)](python/)
[![License](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)
[![Tests](https://img.shields.io/badge/tests-32%20passed-brightgreen.svg)](python/tests/)

---

## 这是什么？

一个**6-Agent 智能教育系统**。拍了数学题上传，AI 不会直接告诉你答案，而是：

1. **识别题目** → Vision LLM 提取题目文字和知识点
2. **苏格拉底式引导** → "你能识别出这是什么函数吗？"而不是"答案是 x=-1"
3. **分级提示** → 卡住了？先给思路暗示，再给步骤引导，实在不行才展示完整答案
4. **追踪掌握度** → 用贝叶斯知识追踪评估你对每个知识点的掌握概率
5. **动态排复习** → SM-2 间隔重复算法，在你快忘的时候安排复习

---

## 6 个 Agent 各做什么

```
┌──────────────────────────────────────────────────────────┐
│                     EventBus (事件总线)                    │
│                                                          │
│  photo.session_started  ←→  PhotoTutorAgent (拍照引导)   │
│  assessment.complete    ←→  AssessmentAgent (BKT评估)    │
│  tutor.teaching         ←→  TutorAgent (苏格拉底教学)     │
│  hint.needed            ←→  HintAgent (3级提示)          │
│  curriculum.path        ←→  CurriculumAgent (SM-2排期)   │
│  engagement.alert       ←→  EngagementAgent (状态监测)   │
└──────────────────────────────────────────────────────────┘
```

| Agent               | 职责                               | 核心算法                |
| ------------------- | ---------------------------------- | ----------------------- |
| **PhotoTutorAgent** | 拍照会话管理 + 引导编排 + 回复评判 | 状态机 (9状态)          |
| **AssessmentAgent** | 知识点掌握度追踪                   | 贝叶斯知识追踪 (BKT)    |
| **TutorAgent**      | 苏格拉底式提问，不直接给答案       | Prompt Engineering      |
| **CurriculumAgent** | 学习路径规划 + 间隔重复排期        | SM-2 + 知识图谱拓扑排序 |
| **HintAgent**       | 3级渐进提示：元认知→脚手架→直接    | 最近发展区 (ZPD)        |
| **EngagementAgent** | 学习状态监测：挫败/无聊/疲劳       | 行为规则引擎            |

### 拍照引导流程

```
上传图片 → Vision LLM 识别 → 分析知识点+拆解题步骤
    → 苏格拉底引导提问
        → 学生答对 → 推进下一步
        → 学生卡住 → L1 元认知提示 → L2 脚手架 → L3 直接提示
        → L3+2次仍错 → 展示完整答案 + 标记弱项
    → BKT 更新掌握度 → SM-2 安排复习
```

---

## 5 分钟跑起来

### 启动后端

```bash
cd multi-agent-education/python

# 安装依赖
pip install -r requirements.txt

# 配置 API Key（可选，不配也能跑 mock 模式）
cp ../.env.example ../.env
# 编辑 ../.env，填入 OPENAI_API_KEY

# 启动服务
uvicorn api.main:app --reload --port 8000
```

### 打开前端

浏览器直接打开：

```
frontend/demo.html
```

或者访问 Swagger API 文档：

```
http://localhost:8000/docs
```

### 快速端到端测试（不启动服务）

```bash
cd python
python quick_test.py
```

---

## 项目结构

```
multi-agent-education/
├── python/
│   ├── agents/                     # 6 个 Agent
│   │   ├── photo_tutor_agent.py    # ★ 拍照引导 Agent
│   │   ├── assessment_agent.py     # BKT 评估
│   │   ├── tutor_agent.py          # 苏格拉底教学
│   │   ├── curriculum_agent.py     # SM-2 排期
│   │   ├── hint_agent.py           # 3级提示
│   │   └── engagement_agent.py     # 状态监测
│   ├── core/
│   │   ├── event_bus.py            # 事件总线 (24 种事件)
│   │   ├── learner_model.py        # BKT 贝叶斯知识追踪
│   │   ├── spaced_repetition.py    # SM-2 算法
│   │   ├── knowledge_graph.py      # 知识图谱 DAG
│   │   ├── ocr_engine.py           # Vision LLM OCR
│   │   ├── problem_analyzer.py     # 题目分析 + 引导问题生成
│   │   ├── photo_session.py        # 拍照会话状态机
│   │   └── student_profile.py      # 学生画像 + SQLite
│   ├── api/
│   │   ├── main.py                 # FastAPI 入口
│   │   ├── orchestrator.py         # Agent 编排器
│   │   ├── routes.py               # REST API (8 端点)
│   │   └── websocket.py            # WebSocket
│   └── tests/                      # 65 个测试
├── frontend/
│   └── demo.html                   # ★ 独立前端 (无需构建)
└── docs/
    ├── architecture.md
    ├── interview-guide.md
    └── knowledge-points.md
```

---

## API 端点

| 方法   | 路径                               | 说明                  |
| ------ | ---------------------------------- | --------------------- |
| `GET`  | `/api/v1/health`                   | 健康检查              |
| `POST` | `/api/v1/photo-solve`              | 📷 上传图片，开始引导 |
| `POST` | `/api/v1/photo-session/{id}/reply` | 💬 回复引导问题       |
| `GET`  | `/api/v1/photo-session/{id}`       | 查询会话状态          |
| `GET`  | `/api/v1/profile/{learner_id}`     | 学生画像 + BKT        |
| `POST` | `/api/v1/submit`                   | 提交答题结果          |
| `POST` | `/api/v1/question`                 | 提问                  |
| `POST` | `/api/v1/message`                  | 发送消息              |
| `GET`  | `/api/v1/progress/{learner_id}`    | 学习进度              |
| `GET`  | `/api/v1/knowledge-graph`          | 知识图谱              |

---

## 核心算法

### SM-2 间隔重复

```
I(1) = 1天, I(2) = 6天, I(n) = I(n-1) × EF
EF' = EF + 0.1 - (5-q) × (0.08 + (5-q) × 0.02)
```

### BKT 贝叶斯知识追踪

```
P(L|correct) = P(L) × (1-P(S)) / [P(L) × (1-P(S)) + (1-P(L)) × P(G)]
P(L|wrong)   = P(L) × P(S) / [P(L) × P(S) + (1-P(L)) × (1-P(G))]
P(L_new) = P(L|obs) + (1 - P(L|obs)) × P(T)
```

四个参数：P(L₀)=0.1 (初始掌握), P(T)=0.15 (学习转移), P(G)=0.2 (猜测), P(S)=0.1 (失误)

---

---

## 开源协议

MIT License — 自由使用、修改、分发。
