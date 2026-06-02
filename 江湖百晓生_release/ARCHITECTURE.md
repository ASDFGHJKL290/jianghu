# 江湖百晓生 v2.0 — 架构文档

> AI 驱动的武侠 NPC 叙事引擎
> 13 个 NPC · ~10000 行 Python · 200 元 API 预算

---

## 一、启动方式

```bash
cd 江湖百晓生_vue
conda activate jianghu
python main.py
# 浏览器打开 http://127.0.0.1:8000
```

---

## 二、目录结构

```
江湖百晓生_vue/
├── main.py              # FastAPI 路由层（~970 行）
├── game.py              # 业务逻辑 + 全局状态 + 持久化（~725 行）
├── tutorial.py          # 新手引导（由 game.py 拆分）
├── combat.py            # 战斗系统（由 game.py 拆分）
├── shop.py              # 商店/道具（由 game.py 拆分）
├── chat.py              # 对话引擎 + 记忆系统 + 情感驱动（~900 行）
├── event_engine.py      # 事件预生成 + 动态路由 + tick 系统（~1900 行）
├── npc_data.py          # 13 个 NPC 配置文件
├── prompts.py           # 所有 LLM prompt 模板
├── quest_data.py        # 任务/章节配置
├── view_db.py           # 数据库查看工具
├── generate_story.py    # 离线剧情生成入口
├── index.html           # 前端入口（Vue 3 CDN）
├── events/              # 事件引擎 SQLite 数据库
│   └── events.db        #   story_nodes / events / npc_experience_log / npc_reflections
├── state/               # JSON 持久化（好感度/背包/邮箱等）
└── static/              # 静态资源（NPC 头像等）
```

---

## 三、服务架构总览

```
浏览器 ←→ FastAPI (main.py)
               │
               ├── game.py ─── 全局状态 + 持久化
               │     ├── tutorial.py ── 新手引导
               │     ├── combat.py ──── 战斗（含平局）
               │     └── shop.py ────── 商店/道具
               │
               ├── chat.py ──── NPC 对话引擎
               │     ├── 情感引擎（PAD 三维）
               │     ├── 三层记忆系统
               │     ├── 动机驱动（Mood→Goal）
               │     └── 知识库 RAG（ChromaDB + bge-large-zh）
               │
               ├── event_engine.py ─── 事件系统
               │     ├── 离线预生成（时间窗）
               │     ├── 三层过滤管道
               │     ├── tick 系统（30 秒）
               │     └── 动态路由打分
               │
               ├── quest_data.py ─── 任务/章节驱动
               └── generate_story.py ── 一次生成入口
```

---

## 四、外部依赖

| 组件 | 用途 | 备注 |
|------|------|------|
| FastAPI + Uvicorn | HTTP 服务 | 127.0.0.1:8000 |
| LangChain (ChatOpenAI) | DeepSeek API 包装器 | model: deepseek-v4-flash |
| ChromaDB | 知识库向量检索 | bge-large-zh-v1.5 embedding |
| SQLite (events.db) | 事件节点持久化 | 预生成数据+运行状态 |
| JSON 文件 (state/) | 玩家状态持久化 | 好感度/背包/邮箱/任务 |
| NetworkX | NPC-地点知识图谱 | 校验剧情合理性 |
| DeepSeek API | 核心 LLM | 对话/生成/评分 |
| 阿里云百炼 (DashScope) | Qwen-Plus | 备用/特定任务 |
| KataGo | 围棋分析（可选） | 嵌入式 GTP 进程 |

---

## 五、核心系统详解

### 5.1 对话引擎（chat.py）

**数据流：**

```
玩家输入
  → 知识库检索（ChromaDB 语义匹配江湖百科）
  → 情感计算（PAD: Pleasure-Arousal-Dominance）
  → 记忆加载（短期 + 长期 + fixed_layer）
  → 动机查询（Mood → Goal 映射）
  → LLM 生成回复
  → 记忆更新（每 5 轮自动总结）
  → 任务检测（_advance_quest_step）
```

**三层记忆系统：**

| 层级 | 存储位置 | 触发条件 | 内容 |
|------|----------|----------|------|
| 短期记忆 | chat_history (内存) | 50 轮内 | 原始对话 |
| 长期记忆（常见） | long_term_memory (dict) | weight > 30 | 经验总结 |
| 长期记忆（罕见·固定） | long_term_memory (dict) | weight > 70 或 fixed_layer | 永不遗忘的关键事件 |

**情感引擎（PAD）：**

- 每次对话后更新 PAD 三维值（Pleasure / Arousal / Dominance）
- 基于对话内容和好感度变化计算
- 情感值衰减：随时间缓慢回归中性

**动机系统：**

- 每个 NPC 有当前 Mood（情绪状态）→ Goal（行为目标）
- Mood 由好感度 + PAD 共同决定
- Goal 映射到 tick 系统的节点偏向

---

### 5.2 事件引擎（event_engine.py）

**离线预生成管线：**

```
generate_story_tree()
  ① 时间窗划分：50 天 ÷ 5 窗 = 每窗 10 天
  ② NPC 分配：每个 NPC 随机分配 3 个窗口
  ③ 批量生成：每个窗口分批调 LLM 生成节点
  ④ 三层过滤：
     a) quality_score < 3 → 丢弃
     b) 与已存在事件语义冲突 → 丢弃
     c) 叙事连贯性不足 → 压制激活优先级
  ⑤ 写入 events.db（story_nodes 表）
```

**tick 系统：**

```
tick() ← 每 30 秒触发（玩家在线时）
  ① 检查 day 推进条件（真实时间 ≥ 游戏时间间隔）
  ② 扫描 pending 节点 → 检查 trigger_json 条件
  ③ 条件通过 → 标记 activated_at
  ④ 收集 condition_edges → 设置"玩家关注方向"
  ⑤ 下一轮 tick 优先激活关注方向的节点
```

**动态路由打分（_resolve_next_nodes）：**

| 维度 | 最高分 | 说明 |
|------|--------|------|
| 地点接近度 | 3 | 玩家已解锁该地点 |
| NPC 好感度 | 5 | 好感 / 10 |
| NPC 接触度 | 2 | 聊过天 |
| 飞鸽情报 | 3 | NPC 传过信 |
| 叙事连续性 | 3 | 和已激活节点有共同 NPC |
| 质量评分 | quality/2 | LLM 自带评分 |
| 相同事件类别 | 1 | / |
| PAD 情感驱动 | 0~4 | 愤怒→冲突 + 消极→旁观 |

---

### 5.3 战斗系统（combat.py）

```
combat_start(npc) → 初始化战斗状态（玩家 100HP, NPC base_hp）
combat_action(action):
  ① 计算玩家伤害（random 10-20）
  ② 计算 NPC 伤害（random 5-15）
  ③ 判定：
     - 双方都 ≤ 0 → draw（平局）
     - 敌人 ≤ 0 → victory（+经验 + 突破判定）
     - 玩家 ≤ 0 → defeat（不停战）
  ④ 返回 combat_result
```

NPC 血量差异化配置（npc_data.py `base_hp`）：

| 低血量 | 中血量 | 高血量 |
|--------|--------|--------|
| 平一指 50 | 店小二 60, 唐巧 70, 任盈盈 80, 欧阳克 90 | 洪七公 110, 瑛姑 85, 风清扬 130, 任我行 120, 黄杉女 100, 扫地僧 150 |

---

### 5.4 任务/章节系统（quest_data.py）

- 任务步骤通过 `_advance_quest_step()` 在对话中检测
- 关键词匹配玩家意图 → 步骤推进 → 任务完成
- 任务完成可能触发 CHAPTER_GATES → 推进章节
- 新章节解锁新地点 → tick 激活新 NPC 的节点

---

### 5.5 故事链（chain_id / chain_step）

- 预生成阶段 LLM 生成 `chain_id`（如"打狗棒失窃"）
- 同 chain_id 的节点按 chain_step 排序形成线性链
- `condition_edges_json` 自动写入 `chain_complete('xxx_stepN')`
- tick 系统检测链条件 → 激活下一节点

---

## 六、数据持久化

### 数据库（events/events.db）

| 表 | 用途 | 关键字段 |
|----|------|----------|
| story_nodes | 预生成+运行时的故事节点 | id, title, from_npc, location, trigger_json, options_json, condition_edges_json, quality_score, status, chain_id, chain_step |
| events | 已激活事件的记录 | title, from_npc, impact_level, status |
| npc_experience_log | NPC 经验记录 | npc_name, experience, importance_score |
| npc_reflections | NPC 反思/洞察 | npc_name, reflection, insight_type |

### JSON 文件（state/）

| 文件 | 用途 |
|------|------|
| player.json | 游戏天数/银两/修为/境界/好感度/邮箱/地图碎片 |
| relations/*.json | NPC 关系（好感度/认知等级） |
| items.json | 背包物品 |
| quests.json | 任务进度 |

---

## 七、前端

- Vue 3 CDN 单页应用（加载快，无构建步骤）
- 功能面板：聊天 / 战斗 / 地图 / 背包 / 邮箱 / NPC 面板 / 围棋分析 / 管理后台

---

## 八、已知架构限制

1. **全局变量耦合** — game.py 的全局状态被 combat.py / tutorial.py / shop.py 依赖，拆分困难
2. **无用户隔离** — 所有状态使用 "default" user_id，不支持多用户
3. **错误处理粗糙** — 部分 except 仍是通用 Exception
4. **预生成 + 实时混合** — 离线事件节点 64 个，LLM 实时对话仍承担叙事连贯性
