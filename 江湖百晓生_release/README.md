# 江湖百晓生 — AI NPC 叙事引擎 demo

> 13 个有独立人格、记忆和情感的 AI NPC，在动态武侠世界中与你自由对话。
> 从头自研的四层记忆系统 + 情感引擎 + 语音交互 + 流式对话。

---

## 五分钟跑起来

### 1. 配环境

```bash
pip install -r requirements.txt
```

### 2. 申请 API Key（免费额度够用）

创建 `.env` 文件（项目根目录），去两个平台各免费注册一下：

```env
# 对话引擎用 — 去 https://platform.deepseek.com 注册，送 500 万 token
DEEPSEEK_API_KEY=sk-你的key
DEEPSEEK_BASE_URL=https://api.deepseek.com

# 语音（TTS/STT）用 — 去 https://bailian.console.aliyun.com 开通百炼，送 100 万 token
DASHSCOPE_API_KEY=sk-你的key
```

> ⚠️ 如果没有阿里云 DashScope key，TTS 语音会跳过，文字对话完全正常。

### 3. 启动

```bash
python main.py
```

浏览器打开 `http://localhost:8000`

---

## 你能看到什么

1. **13 个 NPC**
   店小二、洪七公、风清扬、黄衫女、任盈盈……每个人说话风格、语气完全不同

2. **四层记忆系统**
   你说过的话 NPC 会记住，聊多了有的会固化成"最在意的事"，
   不同的 NPC 关注点不同——店小二更在意八卦，平一指只记伤病

3. **语音交互**
   ﹣ 发消息 → NPC **自动语音回复**（TTS）
   ﹣ 按住麦克风按钮说话 → 语音识别（STT）

4. **流式对话**
   0.5 秒开始出字，不用等

---

## 核心理念（给老师看）

| 点 | 说明 |
|----|------|
| **为什么自研？** | 开源没有成熟的游戏 NPC 记忆系统。所有开源方案要么是通用 AI Agent 的对话缓存，要么是学术论文的理论框架。店小二要记住玩家的八卦、平一指只关心伤病——这种跨 NPC 的个性化记忆策略，现有框架不支持 |
| **四层记忆架构** | 行为层(prompt 规则) / 知识层(RAG 世界观) / 经历层(权重公式) / 社交层(relation.json)。四层各管各的，不打架 |
| **经历层六因子权重** | 每条记忆有 6 个维度的权重：频次 ×0.25 + 重要性 ×0.20 + 情感强度 ×0.15 + 时效 ×0.20 + 感官匹配 ×0.10 + 专业匹配 ×0.10。权重够 5 次自动固化，不再遗忘 |
| **NPC 个性化记忆** | 13 个 NPC 各有四维感官偏好向量(视觉/听觉/逻辑/情感)。黄衫女更易记住玩家衣着(视觉 0.9)，任盈盈更易记住说过的话(听觉 0.9)，平一指只关心伤病相关(专业领域) |
| **情感引擎** | 五维情感状态(喜怒哀惧惊)实时变化，影响 NPC 说话方式和行为动机 |

---

## 项目结构

```
├── main.py          # 服务器入口 + HTTP 路由
├── chat.py          # 对话引擎（LLM 调用 + 记忆检索 + 流式输出）
├── core.py          # 引擎层（情感计算 + 四层记忆 + 动机管理）
├── game.py          # 游戏核心（状态/战斗/地图/日志）
├── npc_data.py      # 13 个 NPC 完整角色数据
├── prompts.py       # 系统提示词模板
├── static/          # 前端页面
│   ├── index.html
│   ├── app.js
│   └── style.css
├── katago/          # 围棋引擎（可忽略，不影响核心功能）
└── requirements.txt
```

---

## 技术栈

| 层 | 技术 |
|----|------|
| 后端 | Python + FastAPI |
| 前端 | Vue 3（CDN SPA） |
| 模型 | DeepSeek V4 Flash + BGE-large-zh |
| 语音 | DashScope CosyVoice TTS + 浏览器原生 STT |
| 存储 | JSON + ChromaDB + SQLite |

---

## 关于作者

软件工程专业，毕业一年，独立完成。
