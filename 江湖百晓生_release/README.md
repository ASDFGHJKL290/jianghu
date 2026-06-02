# 江湖百晓生 v2.0

> 一个基于大语言模型的武侠世界 AI RPG。玩家与 12 位有独立性格、记忆和动机的 NPC 交互，在动态演进的江湖中完成任务、推进事件链、探索地图、对战厮杀。

---

## 核心特色

### 1. 会"活"的 NPC

每个 NPC 不只是根据 prompt 说台词，而是一套完整的 AI NPC 系统：

- **五维情感模型**：每个 NPC 有 valence（愉悦度）、arousal（唤醒度）、dominance（支配度）等实时情感参数，会根据对话内容变化
- **动机驱动**：NPC 有独立的 drive（驱动力）、mood（心情）、goal（目标），驱动其主动行为
- **三层记忆**：NPC 会记住和玩家的互动（日常/罕见/稀有），基于时间衰减和引用频率自动升降级
- **NPC 间社交**：NPC 之间会通过事件链互相触发行为，玩家可能收到 NPC 主动发来的"邮件"

### 2. 动态事件引擎（三层过滤管道）

事件不是硬编码的，而是由 DeepSeek 批量生成后经过三关筛选：

```
DeepSeek 生成 → 语义相似度去重 → 知识图谱校验 → AI 评审团评分 → 入库
```

- **第一层 — 语义过滤**：用 BGE 向量模型检测新事件与已有事件的语义冲突
- **第二层 — 知识图谱校验**：基于 NetworkX 构建的 NPC-地点关系图，过滤违反世界设定的矛盾事件
- **第三层 — AI 评审团**：DeepSeek 对通过的事件评分（合理性/戏剧性/一致性/趣味性），>=5 分才入库

当前总通过率约 64%。

### 3. 事件链系统

多个 NPC 的事件不再孤立，而是构成因果链：
- 洪七公找欧阳克讨说法 → 欧阳克反击 → 第三方 NPC 围观扩散
- 武林盟主察觉九阴真经重现 → 神秘大侠联动调查 → 店小二传播消息
- 事件链中每个步骤会真正注入 NPC 对话 prompt，推动 NPC 按剧情方向自然演进

### 4. 离线预生成（Pregen）

所有故事节点通过 `pregen.py` 离线批量生成，支持多组并行（每组独立的世界线）。服务器启动时从 SQLite 加载，不依赖 LLM 实时生成，保证叙事一致性。

### 5. 围棋死活题系统

集成 KataGo 引擎，提供 9x9 棋盘死活题：
- 玩家落子后自动验证是否命中正解
- 调用 KataGo analysis 模式分析棋盘局势
- 支持 `auto_solve` 自动求解（交替 genmove 直到 Benson 判定死活）

---

## 技术栈

| 层级 | 技术 |
|------|------|
| 后端框架 | FastAPI + Uvicorn |
| 前端 | Vue 3 CDN（单页面） |
| AI 模型 | DeepSeek (deepseek-chat) |
| 向量检索 | ChromaDB + BGE-large-zh |
| 知识图谱 | NetworkX |
| 数据存储 | SQLite（事件/故事节点）+ JSON 文件（状态/记忆/关系） |
| LLM 框架 | LangChain（ChatOpenAI / prompts / output_parsers） |
| 围棋引擎 | KataGo (GTP analysis mode) |

---

## 项目结构

```
江湖百晓生_vue/
├── main.py              # FastAPI 入口 & 所有 HTTP 路由
├── game.py              # 游戏业务逻辑（状态/战斗/背包/商店/地图/新手引导）
├── chat.py              # 核心对话引擎（LLM调用/知识库检索/任务追踪）
├── core.py              # 引擎层（情感/动作/记忆/动机）
├── event_engine.py      # 事件引擎（生成/过滤/事件链/故事树/诊断）
├── game_go.py           # 围棋死活题 & KataGo 分析
├── pregen.py            # 离线预生成工具
├── npc_data.py          # NPC 角色数据（12个NPC + 天气 + 赠礼）
├── quest_data.py        # 任务数据（多步骤任务 + 章节 + 结局）
├── prompts.py           # 系统提示词模板
├── utils.py             # 工具函数
├── static/              # 前端静态资源
│   ├── index.html       # 主页面（Vue3 CDN）
│   ├── app.js           # Vue 主逻辑
│   ├── style.css        # 样式
│   ├── go_tool.html     # 围棋分析工具
│   └── avatars/         # NPC 头像
├── state/               # 游戏状态持久化
│   ├── events.db        # SQLite 事件数据库
│   ├── player.json      # 玩家数据
│   ├── emotions.json    # NPC 情感状态
│   ├── motivations.json # NPC 动机
│   └── mailbox.json     # 玩家邮箱
├── memory/              # 记忆系统
│   ├── longterm/        # NPC 长期记忆
│   ├── relation.json    # 玩家-NPC 关系
│   └── world_state.json # 世界状态
├── jianghu_chroma_db_web/  # ChromaDB 向量库
└── katago/              # KataGo 引擎 & 模型
```

---

## 快速开始

### 环境要求

- Python 3.10+
- 有效 API Key：`DEEPSEEK_API_KEY`、`DASHSCOPE_API_KEY`（可选）
- KataGo（可选，围棋功能需要）

### 安装

```bash
cd 江湖百晓生_vue
pip install -r requirements.txt
```

### 配置

在项目父目录（`day25/`）下创建 `.env`：

```env
DEEPSEEK_API_KEY=sk-xxx
DEEPSEEK_BASE_URL=https://api.deepseek.com
DASHSCOPE_API_KEY=sk-xxx
```

### 预生成故事数据（首次运行前）

```bash
python pregen.py 500   # 生成500个故事节点
```

### 启动

```bash
python main.py
# 访问 http://localhost:8000
```

### KataGo 围棋功能（可选）

1. 下载 KataGo 引擎和模型文件放入 `katago/` 目录
2. 确保路径：`katago/katago.exe`、`katago/kata1-b18c384nbt.bin.gz`、`katago/default_gtp.cfg`

---

## API 概览

### 核心

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/api/chat` | 发送消息给 NPC，返回回复+状态更新 |
| GET | `/api/npcs` | 获取 NPC 列表 |
| GET | `/api/player` | 获取玩家状态（境界/物品/银两） |
| GET | `/api/weather` | 获取当前天气 |
| GET | `/api/game_day` | 获取游戏天数 |

### 任务

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/quests` | 获取任务列表 |
| GET | `/api/quest/progress` | 获取任务进度（含步骤提示） |
| POST | `/api/quest/abandon` | 放弃任务 |

### 战斗

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/api/combat/start` | 开始战斗 |
| POST | `/api/combat/action` | 执行战斗动作 |

### 邮箱

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/mailbox` | 获取收件箱 |
| POST | `/api/mailbox/read` | 标记已读 |

### 事件引擎

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/api/events/generate` | 为 NPC 生成事件 |
| GET | `/api/events/active` | 获取活跃事件 |
| GET | `/api/events/stats` | 获取过滤统计 |
| GET | `/api/diag` | 系统诊断报告 |

### 围棋

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/go/problems` | 获取死活题列表 |
| POST | `/api/go/start/{quest_id}/{problem_id}` | 开始死活题会话 |
| POST | `/api/go/move/{quest_id}` | 落子验证 |
| POST | `/api/go/evaluate/{quest_id}` | 判定死活 |
| POST | `/api/go/analyze` | 独立分析工具 |
| POST | `/api/go/auto-solve` | 自动求解 |

### 其他

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/shop/items` | 商店商品 |
| POST | `/api/shop/buy` | 购买物品 |
| POST | `/api/item/use` | 使用道具 |
| GET | `/api/map/status` | 地图状态 |
| GET | `/api/relation` | NPC 好感度 |
| GET/POST | `/api/tutorial/*` | 新手引导 |

---

## 开发路线图

- [ ] Vite 工程化改造（CDN → 模块化构建）
- [ ] 自动测试框架
- [ ] NPC 语音合成（TTS）
- [ ] 更多地图地点
- [ ] WebSocket 实时推送（事件播报）
- [ ] Docker 部署方案
