# 江湖百晓生

> 一个自研 AI NPC 叙事引擎 — 13 个有独立性格、记忆和动机的 NPC 在动态武侠世界中与玩家自由交互。
>
> **10000+ 行 Python, 45 天独立开发, 单人完成。**

---

## 为什么这个项目值得看

这不是一个套壳 LLM demo。这是一个从头自研的**叙事引擎架构**，核心挑战是：**如何用 LLM 驱动一个叙事自洽、NPC 不串角色、剧情能推演的开放世界？**

主要技术亮点：

- **三层事件过滤管道** — DeepSeek 批量生成 → 向量去重 → 知识图谱校验 → AI 评审团评分，通过率约 64%，API 成本约 200 元完成全量数据生成
- **预生成+时间窗调度** — 不依赖 LLM 实时生成，离线预生成 + 时间窗口调度 + 世界概要传递，保证叙事一致性
- **13 个 NPC 各有独立情感模型** — 五维情感参数实时变化，三层记忆（日常/罕见/稀有）基于时间衰减自动升降级
- **事件链系统** — NPC 事件构成因果链，通过 `condition_edges_json` 拓扑结构驱动剧情演进
- **围棋死活题系统** — 集成 KataGo 引擎，可在 NPC 任务链中触发 9x9 棋盘挑战

---

## 架构

```
┌─────────────────────────────────────────────────────────┐
│                     FastAPI Server                       │
├──────────┬──────────┬───────────┬──────────┬────────────┤
│  chat.py │ game.py  │ core.py   │main.py   │ game_go.py │
│ 对话引擎  │ 游戏逻辑 │ 情感/记忆 │ 路由/状态 │ KataGo围棋  │
├──────────┴──────────┴───────────┴──────────┴────────────┤
│                   event_engine.py                        │
│  事件生成 → 语义去重(ChromaDB) → 知识图谱(NetworkX)     │
│              → AI评审团评分 → 事件链路由                  │
├─────────────────────────────────────────────────────────┤
│           离线层: pregen.py (worldline预生成)              │
│           存储层: SQLite + ChromaDB + JSON               │
│           AI层: DeepSeek + BGE-large-zh + ModelScope      │
└─────────────────────────────────────────────────────────┘
```

### 三层过滤管道（核心）

```
DeepSeek 批量生成 100+ 事件
        │
        ▼
ChromaDB 语义去重
  ← BGE-large-zh 向量化，余弦相似度 > 0.75 判重复
  ← 与历史事件 + 全局事件库双遍去重
        │
        ▼
NetworkX 知识图谱校验
  ← NPC-地点关系图（如 "洪七公→在→丐帮总舵"）
  ← 检查事件中的角色、地点是否匹配当前关系
        │
        ▼
AI 评审团评分
  ← DeepSeek 对 4 个维度打分（合理性/戏剧性/一致性/趣味性）
  ← 总分 ≥ 5 入库，否则丢弃
  ← 通过率约 64%
```

### 预生成架构（Pregen）

```python
# 核心思路：离线生成 + 时间窗口调度
# 不依赖 LLM 实时生成 = 零推理延迟 + 叙事一致性
def pregen_worldline(num_nodes):
    for batch in range(num_nodes // BATCH_SIZE):
        world_summary = build_world_summary(existing_nodes)
        llm_batch = llm.generate(  # 单次 API 调用
            prompt="根据世界概要 {world_summary}，生成 {BATCH_SIZE} 个故事事件..."
        )
        nodes = post_process(llm_batch)  # JSON 解析 + condition_edges 修复
        filtered = pipeline.filter(nodes)  # 三层过滤
        save_to_db(filtered)
```

- 支持多条世界线并行生成
- 世界概要传递 + 时间窗生成 → 保证剧情线性推进
- `condition_edges_json` 自动修复：删除孤立单节点链、重新填充关联边

---

## 技术栈

| 层级 | 技术 |
|------|------|
| 后端 | FastAPI + Uvicorn (Gunicorn 部署就绪) |
| 前端 | Vue 3 CDN（单页面 SPA） |
| 语言模型 | DeepSeek (deepseek-chat) |
| 向量检索 | ChromaDB + BGE-large-zh（ModelScope 自动下载） |
| 知识图谱 | NetworkX（13 NPC × 5 地点关系图） |
| 围棋引擎 | KataGo (GTP analysis mode) — 已预集成 |
| 存储 | SQLite（事件/节点）+ JSON（状态/记忆） |
| LLM 框架 | LangChain (ChatOpenAI + prompts + output_parsers) |

---

## 快速开始

```bash
git clone git@github.com:ASDFGHJKL290/jianghu.git
cd jianghu
pip install -r requirements.txt
```

创建 `.env`（项目根目录）：

```env
DEEPSEEK_API_KEY=sk-xxx
DEEPSEEK_BASE_URL=https://api.deepseek.com
DASHSCOPE_API_KEY=sk-xxx   # 可选，用于备用模型
```

首次需要生成故事数据：

```bash
python pregen.py 500   # 生成 500 个故事节点（约 2-3 分钟，API 费用约 5 元）
```

启动：

```bash
python main.py
# 访问 http://localhost:8000
```

> **说明**：嵌入模型 `BAAI/bge-large-zh-v1.5` 会在首次启动时自动从 ModelScope（魔搭）下载，国内可直接访问。
> KataGo 引擎及权重文件已包含在 `katago/` 目录中，无需额外下载。

---

## 项目结构

```
├── main.py              # FastAPI 入口 & HTTP 路由
├── game.py              # 游戏核心逻辑（状态/战斗/背包/地图/新手引导）
├── chat.py              # 对话引擎（LLM 调用、知识库检索、任务追踪）
├── core.py              # NPC 引擎层（情感模型、记忆系统、动机驱动）
├── event_engine.py      # 事件引擎（生成→过滤→事件链路由→故事树）
├── game_go.py           # KataGo 围棋死活题 & 棋盘分析
├── pregen.py            # 离线预生成工具（worldline 数据）
├── npc_data.py          # 13 个 NPC 完整角色数据
├── quest_data.py        # 多步骤任务系统（章节 + 结局）
├── prompts.py           # 系统提示词模板
├── utils.py             # 工具函数
├── static/              # 前端资源（Vue3 SPA + 围棋工具）
│   ├── index.html       # 主页面
│   ├── app.js           # Vue 前端逻辑
│   ├── style.css        # 全局样式
│   ├── go_tool.html     # 独立围棋分析工具
│   └── avatars/         # NPC 头像
├── katago/              # KataGo 引擎（exe + 权重 + 配置文件）
└── requirements.txt     # Python 依赖
```

---

## NPC 系统

| NPC | 身份 | 位置 | 血量 |
|-----|------|------|------|
| 店小二 | 机灵嘴碎、八卦灵通 | 悦来酒楼 | 60 |
| 武林盟主 (萧千秋) | 威严大气、维护武林秩序 | 武林盟主府 | 120 |
| 神秘大侠 (风无痕) | 神秘话少、守护九阴真经 | 天涯海角 | 100 |
| 扫地僧 | 慈祥淡泊、深藏不露 | 少林寺 | 150 |
| 洪七公 | 丐帮帮主、贪嘴好酒 | 丐帮总舵 | 110 |
| 风清扬 | 华山隐士、独孤九剑传人 | 华山思过崖 | 130 |
| 黄衫女 | 桃花岛传人、精通奇门医术 | 桃花岛 | 100 |
| 唐巧 | 四川唐门高手、冷静寡言 | 四川唐门 | 70 |
| 任盈盈 | 日月神教圣姑 | 黑木崖 | 80 |
| 任我行 | 日月神教前教主、一代枭雄 | 日月神教 | 120 |
| 欧阳克 | 白驼山庄少主、阴险狡诈 | 白驼山庄 | 90 |
| 瑛姑 | 痴情幽怨、算术奇才 | 黑龙潭 | 85 |
| 平一指 | 江湖游医、脾气古怪 | 四处游医 | 50 |

---

## 关于作者

软件工程专业，毕业一年内独立完成。同期另有上线项目：[interview](https://github.com/ASDFGHJKL290/interview) — 基于 FastAPI + LangChain 的 AI 模拟面试工具，已部署至云服务器稳定运行月余。

---

## License

MIT
