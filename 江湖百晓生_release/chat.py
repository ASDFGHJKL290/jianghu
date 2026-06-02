# -*- coding: utf-8 -*-
"""
chat.py — 江湖百晓生 v2.0 核心对话逻辑
JianghuChat 类：整合知识库 / 任务系统 / 情感 / 动作 / 记忆
"""

import os
from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env"))
import os
import random
import re
import json

from langchain_openai import ChatOpenAI
from langchain_core.messages import SystemMessage, HumanMessage
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import StrOutputParser
from langchain_huggingface import HuggingFaceEmbeddings
from langchain_chroma import Chroma
from langchain_community.document_loaders import TextLoader
from langchain_text_splitters import RecursiveCharacterTextSplitter

from utils import sanitize_input, clamp, now_iso
from core import EmotionEngine, ActionParser, MemoryParser, MemoryManager, MotivationManager, _read_json, _write_json
from npc_data import NPC_PROFILES, WEATHER_TYPES, NPC_GIFT_CONFIG
from quest_data import ALL_QUESTS, CHAPTER_CONFIG, OUTCOME_CONFIG
from prompts import (
    RELATION_DELTA,
    EMOTION_RULES, ACTION_RULES, GIFT_RULES, MEMORY_RULES, relation_prompt,
    PERMISSION_LOCK, NO_AI_RULES, mood_behavior_prompt,
    COMBAT_PROMPT, COMBAT_RULES,
)


class JianghuChat:
    def __init__(self):
        api_key = os.getenv("DASHSCOPE_API_KEY")
        base_dir = os.path.dirname(os.path.abspath(__file__))

        # 知识库路径（day25根目录）
        self.knowledge_file = os.path.join(
            os.path.dirname(base_dir), "江湖奇闻轶事知识库.md"
        )
        # Embedding 模型路径
        self.embed_paths = [
            os.path.join(base_dir, "models", "BAAI", "bge-large-zh-v1___5"),
        ]
        self.chroma_dir = os.path.join(base_dir, "jianghu_chroma_db_web")

        # DeepSeek V4 Flash
        ds_key = os.getenv("DEEPSEEK_API_KEY", "")
        ds_base = os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com")
        self._ds_key = ds_key
        self._ds_base = ds_base
        self.llm = ChatOpenAI(
            api_key=ds_key,
            base_url=f"{ds_base}/v1",
            model="deepseek-v4-flash",
            temperature=0.6,   # 历史对话已保证连贯，温度可适当回升
            request_timeout=60,
            max_tokens=400     # 有历史上下文保证连贯，可适度展开
        )

        # 延迟加载
        self._embeddings = None
        self._vector_store = None

        self.weather = self._get_weather()
        self.active_quests = {}   # {user_id: [quest]}
        self.quest_completion = {}  # {user_id: {qid: {title, reward}}}
        self.quest_progress = {}  # {user_id: {qid: {current_step, completed_steps}}}
        self.chapter_progress = {}  # {user_id: {"current_chapter": 1, "completed_chapters": [], "chapter_step": 0}}
        self.outcome_cache = {}     # {user_id: outcome_id} 结局判定缓存，避免重复触发

        self.emotion_engine = EmotionEngine()
        self.action_parser   = ActionParser()
        self.memory_parser   = MemoryParser()
        self.memory = MemoryManager(base_dir)
        self.motivation_manager = MotivationManager(base_dir, NPC_PROFILES)

        # 构建 qid → quest 反向映射（ALL_QUESTS 的 key 是中文名）
        self.qid_to_quest = {}
        for qname, q in ALL_QUESTS.items():
            if "qid" in q:
                self.qid_to_quest[q["qid"]] = q

        # 从持久化存储加载已完成的任务和章节进度
        self._load_persisted_progress()

    # ── 从持久化存储加载进度 ──────────────────────
    def _load_persisted_progress(self):
        """从 world_state.json 加载已完成的任务和章节进度"""
        # 加载已完成的任务（per-user）
        completed = self.memory.get_completed_quests("default")
        for qid in completed:
            if qid not in self.quest_completion.setdefault("default", {}):
                # 从 ALL_QUESTS 中获取任务信息（通过 qid 反向映射）
                quest = self.qid_to_quest.get(qid, {})
                self.quest_completion["default"][qid] = {
                    "title": quest.get("title", ""),
                    "reward": quest.get("reward", ""),
                }

        # 加载章节进度
        ws = _read_json(self.memory.world_file)
        chapter_data = ws.get("chapter_progress", {})
        for uid, prog in chapter_data.items():
            self.chapter_progress[uid] = {
                "current_chapter": prog.get("current_chapter", 1),
                "completed_chapters": prog.get("completed_chapters", []),
                "chapter_step": prog.get("chapter_step", 0),
            }

    def _save_chapter_progress(self, user_id: str = "default"):
        """保存章节进度到持久化存储"""
        ws = _read_json(self.memory.world_file)
        if "chapter_progress" not in ws:
            ws["chapter_progress"] = {}
        ws["chapter_progress"][user_id] = self.get_chapter_progress(user_id)
        _write_json(self.memory.world_file, ws)

    # ── per-user 任务系统 ──────────────────────────
    def _user_quests(self, user_id: str) -> list:
        return self.active_quests.setdefault(user_id, [])

    def _add_quest(self, user_id: str, quest: dict):
        if not any(q.get("qid") == quest.get("qid") for q in self._user_quests(user_id)):
            self._user_quests(user_id).append(quest)

    # ── 延迟加载 Embedding ─────────────────────────
    @property
    def embeddings(self):
        if self._embeddings is None:
            for path in self.embed_paths:
                if os.path.exists(path):
                    self._embeddings = HuggingFaceEmbeddings(model_name=path)
                    break
            else:
                self._embeddings = False
        return self._embeddings or None

    @property
    def vector_store(self):
        if self._vector_store is None:
            self._init_vector_store()
        return self._vector_store

    def _init_vector_store(self):
        try:
            emb = self.embeddings
            if emb is None:
                raise FileNotFoundError("Embedding 模型不可用")
            self._vector_store = Chroma(
                persist_directory=self.chroma_dir,
                embedding_function=emb
            )
            self._vector_store.similarity_search("test", k=1)
            print(f"   [知识库] 已加载 {self.chroma_dir}")
        except Exception:
            try:
                emb = self.embeddings
                if emb is None:
                    raise FileNotFoundError("Embedding 模型不可用，跳过知识库")
                loader = TextLoader(self.knowledge_file, encoding="utf-8")
                docs = loader.load()
                splitter = RecursiveCharacterTextSplitter(chunk_size=512, chunk_overlap=50)
                chunks = splitter.split_documents(docs)
                self._vector_store = Chroma.from_documents(
                    documents=chunks, embedding=emb, persist_directory=self.chroma_dir
                )
                print(f"   [知识库] 从 {self.knowledge_file} 重建完成")
            except Exception as e:
                self._vector_store = False
                print(f"   [知识库] 不可用（{e}），对话功能不受影响")

    def _get_weather(self):
        today = random.choice(list(WEATHER_TYPES.keys()))
        d = WEATHER_TYPES[today].copy()
        d["type"] = today
        d["date"] = "今日"
        return d

    def search_knowledge(self, q: str):
        try:
            if not self.vector_store:
                return None
            docs = self.vector_store.similarity_search(q, k=2)
            return "\n".join(d.page_content for d in docs) if docs else None
        except Exception:
            return None

    def _is_quest_completed(self, user_id: str, qid: str) -> bool:
        """检查任务是否已完成（内存 + 持久化）"""
        # 1. 检查内存中的完成状态
        if self.quest_completion.get(user_id, {}).get(qid):
            return True
        # 2. 检查持久化存储（per-user）
        if qid in self.memory.get_completed_quests(user_id):
            # 同步到内存
            quest = self.qid_to_quest.get(qid, {})
            self.quest_completion.setdefault(user_id, {})[qid] = {
                "title": quest.get("title", ""),
                "reward": quest.get("reward", ""),
            }
            return True
        return False

    def check_quests(self, user_input: str, npc_name: str, user_id: str = "default") -> list:
        user_lower = user_input.lower()
        candidates = []
        for quest_name, q in ALL_QUESTS.items():
            # 跳过非任务配置（NPC配置、章节配置等）
            if "trigger" not in q or "qid" not in q:
                continue
            qid = q["qid"]  # 用 q["qid"] 而不是 dict key
            if npc_name not in q["npc_permission"]:
                continue
            if self._is_quest_completed(user_id, qid):
                continue
            prereq = q.get("prerequisite")
            if prereq:
                # prerequisite 存储的是中文任务名（dict key），需要映射到 qid
                prereq_quest = ALL_QUESTS.get(prereq)
                prereq_qid = prereq_quest["qid"] if prereq_quest else prereq
                if not self._is_quest_completed(user_id, prereq_qid):
                    continue  # 前置任务未完成
            if any(quest.get("qid") == qid for quest in self._user_quests(user_id)):
                continue
            matched = [kw for kw in q["trigger"] if kw.lower() in user_lower]
            if matched:
                candidates.append((len(matched), qid, q))
        if not candidates:
            return []
        candidates.sort(reverse=True, key=lambda x: (x[0], len(x[2]["trigger"])))
        best_qid, best_q = candidates[0][1], candidates[0][2]
        return [{"qid": best_qid, **best_q}]

    def _reply_ok(self, reply: str, npc_name: str) -> bool:
        """输出质量校验：检测明显胡言乱语、空回复、角色混淆"""
        if not reply or len(reply.strip()) < 3:
            return False
        r = reply.strip()
        # 完全相同的重复字符（如"哈哈哈..."）
        if len(set(r)) < 3 and len(r) > 5:
            return False
        # AI 自曝话术
        for bad in ["作为AI", "AI语言模型", "人工智能", "我是一个AI",
                     "根据系统设定", "根据提示词", "按照设定", "我是一个语言模型"]:
            if bad in r:
                return False
        # 输出了自己的名字标签
        for tag in ["(系统)", "[系统]", "(提示)", "[提示]", "System:", "Assistant:"]:
            if tag in r:
                return False
        return True

    def _strip_json_suffix(self, text: str) -> str:
        """去掉 LLM 输出末尾的 JSON 块（emotion / actions / combat）及残留标记"""
        stripped = text.strip()
        # 先清理常见残留标记
        for junk in ["输出：", "输出:", "Output:", "→ 输出:", "→ 输出："]:
            if stripped.endswith(junk):
                stripped = stripped[:-len(junk)].strip()
            # 也处理中间出现的（JSON被剥离后残留）
            idx = stripped.rfind(junk)
            if idx > len(stripped) - len(junk) - 10 and idx > 3:
                stripped = stripped[:idx].strip()
        if not stripped:
            return stripped

        # 方式 A-1：精确标记匹配（含战斗JSON {"hp":...）
        for marker in ['{"emotion"', '{"emotion":', '{"actions"', '{"action":',
                       '{"memory"', '{"memory":', "{'emotion'", "{'emotion':", "{'actions'}",
                       '{\"hp\":', '{\"hp\":']:
            idx = stripped.rfind(marker)
            if idx > 3:
                before = stripped[idx - 1]
                if before in ("\n", "\r", " ", "\t"):
                    return stripped[:idx].strip()

        # 方式 A-2：换行后的 JSON 起始
        for i in range(len(stripped) - 1, -1, -1):
            if stripped[i] == "{" and i > 0:
                j = i - 1
                while j >= 0 and stripped[j] in (" ", "\t"):
                    j -= 1
                if j >= 0 and stripped[j] in ("\n", "\r"):
                    prefix = stripped[:j + 1].strip()
                    suffix = stripped[i:]
                    if len(prefix) < len(stripped) * 0.3:
                        continue
                    suffix_lower = suffix.lower()
                    if any(kw in suffix_lower for kw in ["emotion", "action", "primary", "intensity", "valence"]):
                        return prefix
                    break

        # 方式 B：兜底
        last_nl = max(stripped.rfind("\n"), stripped.rfind("\r"))
        if last_nl > 0:
            suffix = stripped[last_nl:].lower()
            if "emotion" in suffix or "action" in suffix or "memory" in suffix:
                return stripped[:last_nl].strip()
        # 清理LLM输出的HP计算过程
        hp_pats = [
            r'(?m)^[ 	]*[-=*·•].*HP.*\d+[→\-+=].*\d+.*$',
            r'(?m)^\*\*.*HP计算.*\*?$',
            r'(?m)^.*(?:玩家|敌人|敌方|我方)?\s*HP[：:\s]*\d+\s*[→\-]+\s*\d+.*$',
        ]
        for pat in hp_pats:
            stripped = re.sub(pat, '', stripped).strip()
        stripped = re.sub('\n{3,}', '\n\n', stripped)

        return stripped

    def _extract_combat_json(self, text: str) -> dict:
        """从LLM输出中提取战斗结果JSON"""
        import re
        # 匹配战斗状态JSON
        pattern = r'\{"hp":\s*\d+,\s*"enemy_hp":\s*\d+,\s*"status":\s*"[^"]+"\}'
        match = re.search(pattern, text)
        if match:
            try:
                return json.loads(match.group())
            except Exception:
                pass
        return {"hp": 100, "enemy_hp": 100, "status": "ongoing"}

    def _strip_combat_json(self, text: str) -> str:
        """去掉战斗叙事末尾的JSON块，只保留武侠叙事文本"""
        if not text:
            return text
        stripped = text.strip()
        # 去掉末尾的JSON块（各种格式）
        patterns = [
            r'\{"hp"\s*:\s*\d+\s*,\s*"enemy_hp"\s*:\s*\d+\s*,\s*"status"\s*:\s*"[^"]+"\}',
            r'\{\s*"hp"\s*:\s*\d+\s*,\s*"enemy_hp"\s*:\s*\d+\s*,\s*"status"\s*:\s*"[^"]+"\s*\}',
            r"\{'hp'\s*:\s*\d+\s*,\s*'enemy_hp'\s*:\s*\d+\s*,\s*'status'\s*:\s*'[^']+'\s*\}",
            r"\n\s*\{.*\}\s*$",
        ]
        for pat in patterns:
            stripped = re.sub(pat, '', stripped, flags=re.DOTALL).strip()
        return stripped

    def chat(self, user_input: str, history: list, npc_name: str, user_id: str = "default", combat_mode: bool = False) -> dict:
        """
        返回完整响应 dict：
        reply / emotion_state / actions / new_quests /
        memory_update / relation_change / new_relation / _history
        """
        profile = NPC_PROFILES.get(npc_name, NPC_PROFILES["店小二"])
        status, clean = sanitize_input(user_input)

        if status != "ok":
            reply = random.choice(profile["fallback_replies"][status])
            return {
                "reply": reply,
                "emotion_state": self.emotion_engine._default(),
                "actions": ["idle"],
                "new_quests": [],
                "memory_update": {"relation_change": {npc_name: 0}},
                "relation_change": 0,
                "new_relation": self.memory.get_relation("default", npc_name),
                "_history": history,
            }

        # 任务检测
        triggered_quests = self.check_quests(clean, npc_name, user_id)
        # 章节进度检查
        chapter_advancement = self.check_chapter_advancement(clean, npc_name, user_id)

        # 任务文本
        if triggered_quests:
            q = triggered_quests[0]
            quest_text = (
                f"\n【系统任务已触发】\n━━━━━━━━━━━━━━━━\n"
                f"✦ 任务名称：{q['title']}\n"
                f"✦ 任务描述：{q['desc']}\n"
                f"✦ 任务奖励：{q['reward']}\n"
                f"━━━━━━━━━━━━━━━━\n"
                f"【必须严格按格式发布，不得自创、不得修改内容】\n"
                f"【任务发布】\n✦ 任务名称：{q['title']}\n"
                f"✦ 描述：{q['desc']}\n✦ 奖励：{q['reward']}\n——{npc_name}\n"
            )
        else:
            quest_text = "【本次未触发任务，严禁编造任何任务】"

        # 进行中任务步骤引导
        step_guidance = ""
        for quest in self._user_quests(user_id):
            qid = quest.get("qid")
            prog = self.quest_progress.get(user_id, {}).get(qid)
            if prog and quest.get("steps"):
                step_idx = prog["current_step"] - 1
                if 0 <= step_idx < len(quest["steps"]):
                    step = quest["steps"][step_idx]
                    is_chain = quest.get("type") == "chain"
                    guidance = "自然引导玩家聊到相关话题完成此步骤"
                    if is_chain and step.get("hint"):
                        guidance += f"，暗示玩家{step['hint']}"
                    step_guidance += (
                        f"\n【当前任务·{quest['title']}（{step['id']}/{len(quest['steps'])}）】"
                        f"待完成：{step['desc']}（{guidance}）\n"
                    )

        # 打工检测（仅店小二）
        work_reward = 0
        if npc_name == "店小二":
            work_kw = ["打工", "赚银子", "赚钱", "杂活", "干活", "帮工", "打杂", "零工", "活干",
                       "找点活", "有活吗", "能不能赚"]
            if any(kw in clean for kw in work_kw):
                import game as g2
                result = g2.try_work_at_tavern()
                if result is not None:
                    work_reward = result
                    quest_text += (
                        f"\n【系统指令】玩家想打短工赚银子，你给他安排个合适的杂活"
                        f"（端盘子、扫地、跑腿、帮厨都行），完事后付他{work_reward}两银子。"
                        f"自然融入对话，表情和语气保持你店小二的人设，别生硬。\n"
                    )

        # 知识库（短文本/问候不搜）
        short_patterns = [
            "你好", "你好呀", "你好啊", "在吗", "哈哈", "嗯", "哦",
            "嗨", "拜", "再见", "干嘛", "咋了", "有事", "没事",
            "说说", "聊聊", "随便", "随便吧",
        ]
        if len(clean) < 8 or any(p in clean for p in short_patterns):
            kb_text = ""
        else:
            knowledge = self.search_knowledge(clean)
            kb_text = f"\n\n【江湖见闻】\n{knowledge}" if knowledge else ""
        weather_str = (f"【今日天气】{self.weather['date']} "
                       f"{self.weather['type']}：{self.weather['desc']}")

        # 对话历史 —— 从memory读完整记录（已有save_turn写入），不用前端传来的截断版
        chat_history = self.memory.get_short_term(npc_name)
        chat_hist_text = ""
        if chat_history:
            # 检测会话边界：距上条记录超过30分钟为新会话
            session_boundary = False
            if len(chat_history) >= 2:
                last_ts = chat_history[-1].get("timestamp", "")
                prev_ts = chat_history[-2].get("timestamp", "")
                try:
                    from datetime import datetime
                    t1 = datetime.fromisoformat(last_ts)
                    t2 = datetime.fromisoformat(prev_ts)
                    if abs((t1 - t2).total_seconds()) > 1800:
                        session_boundary = True
                except Exception:
                    pass
            # 上次会话摘要（仅在新会话开始时注入）
            session_summary = ""
            if session_boundary and len(chat_history) >= 2:
                first_of_last = chat_history[0].get("user", "")[:40]
                if first_of_last:
                    session_summary = f"【上次对话】上次你来找我说的是：{first_of_last}……\n"

            recent = chat_history[-8:]  # 最近8轮（16条消息），1M上下文随便装
            lines = []
            for t in recent:
                user_msg = t.get("user", "")
                assistant_msg = t.get("assistant", "")
                if user_msg:
                    lines.append(f"玩家：{user_msg}")
                if assistant_msg:
                    lines.append(f"你（{npc_name}）：{assistant_msg}")
            if lines:
                chat_hist_text = session_summary + "【对话历史 · 你刚才说过的话，请保持前后一致】\n" + "\n".join(lines)

        # 亲密度
        intimacy = self.memory.get_relation("default", npc_name)

        # NPC 动机状态（战斗和普通对话都需要）
        mot = self.motivation_manager.get(npc_name)
        motivation_text = (
            f"\n【当前状态】\n"
            f"心情：{mot['mood']}\n"
            f"驱动力：{mot['drive']}\n"
            f"当前目标：{mot['goal']}\n"
        )
        mood_text = mood_behavior_prompt(mot.get("mood", "平静"))

        # 统一记忆块（两层长期记忆 + session短期）
        # 长期：不常用=经历 / 稀缺=最在意的事
        # 短期：近期对话（session历史截断）
        ltm = self.memory.get_longterm(npc_name)
        all_events = ltm.get("key_events", [])
        uncommon = [e["event"] for e in all_events if e.get("layer") == "uncommon"][-4:]
        rare    = [e["event"] for e in all_events if e.get("layer") == "rare"][-2:]
        mem_parts = []
        if rare:
            mem_parts.append("【最在意的事】\n" + "\n".join(f"- {e}" for e in rare))
        if uncommon:
            mem_parts.append("【经历】\n" + "\n".join(f"- {e}" for e in uncommon))
        ltm_text = "\n\n".join(mem_parts) if mem_parts else ""

        # 记录被检索到的记忆（触发权重增长 + 衰减 + 升降级）
        try:
            self.memory.record_references(npc_name, uncommon + rare)
        except AttributeError:
            pass  # 兼容旧版 MemoryManager

        # 构建 Prompt（根据战斗模式选择）
        if combat_mode:
            system_content = (
                profile["system_prompt"] + "\n\n"
                + PERMISSION_LOCK.format(npc_name=npc_name) + "\n\n"
                + motivation_text + mood_text + "\n\n"
                + NO_AI_RULES + "\n\n"
                + relation_prompt(npc_name, intimacy) + "\n\n"
                + COMBAT_PROMPT + "\n\n"
                + COMBAT_RULES
            )
        else:
            # 章节上下文

            # 章节上下文
            from quest_data import CHAPTER_CONFIG
            import game as g
            prog = self.get_chapter_progress()
            chapter_id = prog.get("current_chapter", 1)
            chapter_info = CHAPTER_CONFIG.get(f"chapter_{chapter_id}", {})
            chapter_text = (
                f"\n【当前章节：第{chapter_id}章 {chapter_info.get('name', '')}】\n"
                f"本章背景：{chapter_info.get('desc', '江湖风云变幻中')}\n"
            ) if chapter_info else ""

            system_content = (
                profile["system_prompt"] + "\n\n"
                + PERMISSION_LOCK.format(npc_name=npc_name) + "\n\n"
                + motivation_text + mood_text + chapter_text + "\n\n"
                + NO_AI_RULES + "\n\n"
                + relation_prompt(npc_name, intimacy) + "\n\n"
                + GIFT_RULES + "\n\n"
                + EMOTION_RULES + "\n\n"
                + ACTION_RULES + "\n\n"
                + MEMORY_RULES
            )

        # 注入 NPC 可赠物品列表
        npc_cfg = NPC_GIFT_CONFIG.get(npc_name, {})
        gift_items = npc_cfg.get("items", [])
        if gift_items:
            gift_avail = "\n".join([f"  - {g['name']}({g['icon']})：{g.get('desc', '')}" for g in gift_items])
            gift_context = f"\n【NPC赠礼配置】\n你可赠送以下物品（从列表中选，不要自创）：\n{gift_avail}\n赠礼风格：{npc_cfg.get('style', '热情')}"
        else:
            gift_context = ""
        
        # 注入玩家状态信息（用于NPC情境感知馈赠）
        import game
        realm_name = game.get_realm_info(game.exp)["name"]
        items_desc = "、".join(
            f"{it['name']}x{it.get('count',1)}" for it in game.player_items
        ) if game.player_items else "（暂无）"
        uid = user_id or "default"
        aq_list = self.active_quests.get(uid, [])
        tasks_desc = ""
        if aq_list:
            task_lines = []
            for q in aq_list:
                qp = self.quest_progress.get(uid, {}).get(q["qid"], {})
                cur = qp.get("current_step", 0) + 1
                total = len(q.get("steps", []))
                task_lines.append(f"  · {q['title']}（第{cur}/{total}步）")
            tasks_desc = "\n活跃任务：\n" + "\n".join(task_lines)
        player_status = (
            f"\n【玩家状态】\n"
            f"银两：{game.silver}两 | 境界：{realm_name} | 修为经验：{game.exp}\n"
            f"道具：{items_desc}\n"
            f"与{npc_name}的亲密度：{intimacy}{tasks_desc}\n"
            f"\n【世界规则】你只能让玩家去【找其他NPC聊天】，不要叫玩家去某个地方探索或查看——"
            f"这个世界没有可自由走动的地图，玩家只能通过对话与NPC互动。\n"
        )
        # 事件上下文（普通事件 + 活跃事件链步骤 + 反思内心独白）
        event_context = ""
        try:
            em = getattr(self, "event_manager", None)
            if em is not None:
                event_context = em.get_events_for_context(npc_name)
                chain_ctx = em.get_chain_context_for_npc(npc_name)
                if chain_ctx:
                    event_context += chain_ctx
                # 注入反思内心独白（让NPC对话带有思考深度）
                reflect_ctx = em.get_reflection_context_for_npc(npc_name)
                if reflect_ctx:
                    event_context += reflect_ctx
        except Exception as e:
            print(f"[Chat] 事件上下文获取失败: {e}")

        # 飞鸽情报：玩家已知的江湖动态（从已读消息中提取，限3条）
        mail_context = ""
        try:
            import game as _gm
            read_npcs = _gm.get_read_mail_npcs("default")
            if npc_name in read_npcs:
                mailbox_data = _gm._load_mailbox()
                recent_mails = [
                    m for m in mailbox_data.get("default", [])
                    if m.get("read") and m.get("from_npc") == npc_name
                ][-3:]  # 最近3条已读飞鸽
                if recent_mails:
                    mail_lines = [f"【玩家已知情报】{npc_name}曾通过飞鸽传书告知："]
                    for m in recent_mails:
                        mail_lines.append(f"  · {m.get('content', '')}")
                    mail_context = "\n".join(mail_lines) + "\n"
        except Exception:
            pass

        human_content = (
            f"{weather_str}\n{kb_text}\n{chat_hist_text}\n{ltm_text}\n{gift_context}\n{player_status}"
            f"\n{event_context}\n{mail_context}\n{quest_text}\n\n"
            f"{step_guidance}\n【当前对话】\n玩家：{clean}"
        )

        prompt = ChatPromptTemplate.from_messages([
            SystemMessage(content=system_content),
            HumanMessage(content=human_content),
        ])

        # LLM 调用（带简单重试，最多3次）
        raw = None
        last_error = None
        for attempt in range(3):
            try:
                raw = (prompt | self.llm | StrOutputParser()).invoke({})
                break
            except Exception as e:
                last_error = e
                if attempt < 2:
                    import time as _time
                    _time.sleep(1.5 * (attempt + 1))
        if raw is None:
            print(f"[Chat] LLM调用失败（重试3次耗尽）: {last_error}")
            raw = (f"（{npc_name}眉头一皱）江湖信号不佳，"
                   f"{npc_name}一时走神……请少侠稍后再试。")

        # 提取回复（去 JSON）
        reply = self._strip_json_suffix(raw)
        
        # 输出质量校验：检测明显错误，触发降级重试
        if not self._reply_ok(reply, npc_name) and attempt < 2:
            # 提高温度重试一次（有时太低的温度会导致死循环）
            temp_llm = ChatOpenAI(
                api_key=self._ds_key,
                base_url=f"{self._ds_base}/v1",
                model="deepseek-v4-flash",
                temperature=0.8,
                request_timeout=60,
                max_tokens=300
            )
            try:
                raw2 = (prompt | temp_llm | StrOutputParser()).invoke({})
                if raw2:
                    reply = self._strip_json_suffix(raw2)
            except Exception:
                pass
        
        # 提取礼物信息
        gift_info = self._extract_gift(raw)
        if gift_info:
            reply = self._strip_gift(reply)
        
        # 战斗模式下提取战斗结果JSON
        combat_result = None
        if combat_mode:
            combat_result = self._extract_combat_json(raw)

        # 情感 & 动作
        emotion_state = self.emotion_engine.infer(raw, npc_name)
        actions = self.action_parser.parse(raw)

        # LLM 记忆提取 → 写入长期记忆
        memory_text = self.memory_parser.parse(raw)
        if memory_text:
            self.memory.update_longterm(npc_name, memory_text)

        # 记忆持久化
        rel_delta = RELATION_DELTA.get(emotion_state["primary"], 0)
        if intimacy < 30 and emotion_state["primary"] in ["angry", "disgusted", "fearful"]:
            rel_delta = max(rel_delta, -2)

        # 亲密度本地计算 + 持久化（两处 clamp 结果一致，
        # 避免 try-except 包裹 save_turn 导致 new_relation 丢失）
        new_relation = clamp(intimacy + rel_delta, 0, 100)
        memory_update = self.memory.save_turn(npc_name, {
            "user": clean,
            "assistant": reply,
            "emotion": emotion_state["primary"],
            "intensity": emotion_state["intensity"],
            "relation_delta": rel_delta,
            "timestamp": now_iso(),
        })

        # 对话概要：每5轮保存一次上次对话主题到长期记忆
        chat_history = self.memory.get_short_term(npc_name)
        if chat_history and len(chat_history) % 5 == 0:
            first_msg = chat_history[0].get("user", "")[:60]
            last_reply = chat_history[-1].get("assistant", "")[:60]
            if first_msg:
                self.memory.update_longterm(
                    npc_name, f"【聊天记录】上次玩家来找我聊：{first_msg}，我回应了：{last_reply}",
                    layer="uncommon"
                )

        # 任务加入活跃列表
        for q in triggered_quests:
            self._add_quest(user_id, q)
            # 初始化任务进度
            if "steps" in q:
                self.quest_progress.setdefault(user_id, {})[q["qid"]] = {
                    "current_step": 1,
                    "completed_steps": []
                }
            self.memory.update_longterm(npc_name, f"触发任务：{q['title']}")

        # 任务步骤推进
        step_completions, quest_completions = self._advance_quest_step(clean, npc_name, user_id)
        for sc in step_completions:
            self.memory.update_longterm(npc_name, f"任务步骤完成：{sc['title']} - {sc['step_desc']}")
        for qc in quest_completions:
            self.memory.update_longterm(npc_name, f"任务完成：{qc['title']}！奖励：{qc['reward']}", layer="rare")
        # 关卡任务完成 → 覆盖章节推进信息
        for qc in quest_completions:
            if qc.get("chapter_advance"):
                chapter_advancement = {
                    "advanced": True,
                    "new_chapter": qc["chapter_advance"],
                    "auto_advanced": True,
                    "completed_all": False,
                }
        # 情感强度 > 0.7 → 写入长期记忆（稀缺层）
        if emotion_state["intensity"] >= 0.7 and emotion_state["trigger_word"]:
            self.memory.update_longterm(npc_name, f"情感波动：{emotion_state['primary']}（{emotion_state['trigger_word']}）", layer="rare")

        new_history = history + [
            {"role": "user",      "content": clean},
            {"role": "assistant", "content": reply},
        ]

        # 检测是否有待解决的围棋死活题步骤
        go_problem = self._get_pending_go_step(user_id)

        # 提取结局信息（来自任务完成回调）
        outcome_info = None
        for qc in quest_completions:
            if qc.get("outcome"):
                outcome_info = qc["outcome"]
                break

        return {
            "reply": reply,
            "emotion_state": emotion_state,
            "actions": actions,
            "new_quests": triggered_quests,
            "memory_update": memory_update,
            "relation_change": rel_delta,
            "new_relation": new_relation,
            "combat_result": combat_result,
            "quest_step_completed": step_completions,
            "quest_completed": quest_completions,
            "outcome_info": outcome_info,
            "chapter_advancement": chapter_advancement,
            "gift": gift_info,
            "work_reward": work_reward,
            "go_problem": go_problem,
            "_history": new_history,
        }


    def generate_mail_message(self, npc_name: str, motivation: dict) -> str:
        """用 LLM 生成 NPC 主动发给玩家的自然消息"""
        prompt = (
            f"你扮演{npc_name}。\n"
            f"当前心情：{motivation.get('mood', '平静')}。\n"
            f"你的驱动力：{motivation.get('drive', '')}。\n"
            f"当前目标：{motivation.get('goal', '')}。\n"
            f"你想主动联系玩家传达一件事。\n"
            f"请写一条30字以内的自然消息，要像江湖中人平常说话的语气，不要书面化。\n"
            f"只输出消息内容，不要加引号或说明。"
        )
        try:
            mail_prompt = ChatPromptTemplate.from_messages([
                HumanMessage(content=prompt),
            ])
            raw = (mail_prompt | self.llm | StrOutputParser()).invoke({})
            return raw.strip()[:60]
        except Exception:
            return f"（{npc_name}似乎有话想说，但还没来得及传信）"


    def combat_chat(self, npc_name: str, action: str, player_hp: int, enemy_hp: int,
                      player_dmg: int, enemy_dmg: int, status: str,
                      combat_history: str = "", background: str = "") -> str:
        """
        生成战斗叙事描述。
        所有伤害数值由系统（game.py）计算后传入，LLM 只负责写武侠叙事。
        combat_history: 之前轮次的叙事文本（保持前后连贯）
        background: 战斗开场/背景（为什么打）
        """
        profile = NPC_PROFILES.get(npc_name, NPC_PROFILES["店小二"])
        # NPC 动机+情绪（战斗中保持一致）
        mot = self.motivation_manager.get(npc_name)
        motivation_text = (
            f"\n【当前状态】心情：{mot['mood']} | 驱动力：{mot['drive']} | 目标：{mot['goal']}\n"
        )
        mood_text = mood_behavior_prompt(mot.get("mood", "平静"))
        intimacy = self.memory.get_relation("default", npc_name)
        
        action_text = {
            "attack": "正面强攻",
            "trick":  "虚晃一枪，声东击西",
            "retreat":"试图脱身撤退",
        }.get(action, "发起进攻")

        # 动作风格差异化引导
        action_guide = {
            "attack": (
                "【本轮战术：正面强攻】\n"
                "玩家选择硬碰硬、以力破力。你应描写刀剑相撞、火花四溅、双方内力对撼的场面。\n"
                "描写要点：招式凌厉、气势如虹、硬桥硬马、不留余地。\n"
                "对方反击时：正面招架、你争我夺、谁也不退让。"
            ),
            "trick": (
                "【本轮战术：虚实结合·智取】\n"
                "玩家选择以智取胜、诱敌深入。你应描写虚晃诱敌、声东击西、趁机偷袭的场面。\n"
                "描写要点：虚实相生、诱敌入伏、趁虚而入、兵不厌诈。\n"
                "对方反应：中了圈套、措手不及、陷入被动。"
            ),
            "retreat": (
                "【本轮战术：寻隙脱身】\n"
                "玩家不恋战、伺机撤退。你应描写玩家观察破绽、边挡边退、寻隙脱身的场面。\n"
                "描写要点：保存实力、知进退、看清形势、不硬撑。\n"
                "战斗是否成功逃脱，取决于status：escape=成功，ongoing=还在打。"
            ),
        }.get(action, "【本轮战术：进攻】玩家发起进攻。")

        system_content = (
            profile["system_prompt"] + "\n\n"
            + PERMISSION_LOCK.format(npc_name=npc_name) + "\n\n"
            + motivation_text + mood_text + "\n\n"
            + NO_AI_RULES + "\n\n"
            + relation_prompt(npc_name, intimacy) + "\n\n"
            + COMBAT_PROMPT + "\n\n"
            + COMBAT_RULES
        )

        new_player_hp = max(0, player_hp - enemy_dmg)
        new_enemy_hp = max(0, enemy_hp - player_dmg)

        human_content = (
            f"【本轮战斗由系统计算伤害，LLM只负责叙事】\n\n"
            f"{'【战斗背景】' + background + chr(10) if background else ''}"
            f"{'【前情提要 · 刚才发生了什么】' + chr(10) + combat_history + chr(10) if combat_history else ''}"
            f"当前状态：\n"
            f"- 玩家HP：{player_hp} → 受到 {enemy_dmg} 点伤害 → {new_player_hp}\n"
            f"- 敌人HP：{enemy_hp} → 受到 {player_dmg} 点伤害 → {new_enemy_hp}\n"
            f"- 战斗结果：{status}\n\n"
            f"{action_guide}\n\n"
            f"请基于以上数值和战术，写一段武侠风格的战斗叙事（100-200字），不要提及具体伤害数字，"
            f"只描写动作、招式、交锋场面。"
            f"{' 战斗已结束，请总结收尾。' if status != 'ongoing' else ''}\n"
            f"末尾输出一行JSON：{{\"hp\":{new_player_hp},\"enemy_hp\":{new_enemy_hp},\"status\":\"{status}\"}}"
        )

        prompt = ChatPromptTemplate.from_messages([
            SystemMessage(content=system_content),
            HumanMessage(content=human_content),
        ])

        try:
            raw = (prompt | self.llm | StrOutputParser()).invoke({})
            stripped = self._strip_combat_json(raw)
            if not stripped or len(stripped) < 10:
                raise ValueError(f"LLM返回内容过短: {repr(stripped)}")
            return stripped
        except Exception as e:
            # 打印到 stderr，方便排查
            import sys; print(f"[combat_chat ERROR] {type(e).__name__}: {e}", file=sys.stderr)
            fallback = {
                "ongoing":  f"你{action_text}，招式凌厉！对方也不甘示弱，双方你来我往，激战数合。",
                "victory":   f"你{action_text}，最后一招正中对方要害！敌人轰然倒地，你大获全胜！",
                "defeat":    f"你{action_text}，然而对方招招致命，你渐渐体力不支，最终不支倒地……",
                "escape":    f"你{action_text}，趁对方破绽之际纵身跃出战圈，成功脱身！",
            }
            return fallback.get(status, "双方激战，胜负未分。")

    def _advance_quest_step(self, user_input: str, npc_name: str, user_id: str):
        """根据用户输入推进任务步骤。返回 (step_completions, quest_completions)。"""
        user_lower = user_input.lower()
        step_completions = []
        quest_completions = []
        CHAPTER_GATES = {
            "jiu_lou_mi_tan": 2,          # 酒楼密谈完成 → 第2章（第1章→第2章）
            "di_tu_pin_he": 3,             # 地图拼合完成 → 第3章（第2章→第3章，丐帮风云→地图拼合桥接）
            "men_pai_da_hui": 4,          # 门派大会完成 → 第4章（第3章→第4章）
            "ren_wo_xing_zhi_zhi_wen": 5, # 任我行的质问完成 → 第5章（第4章→第5章）
            "zhen_xiang_da_bai": 6,       # 真相大白完成 → 第6章（第5章→第6章）
        }

        for quest in list(self._user_quests(user_id)):
            qid = quest.get("qid")
            steps = quest.get("steps", [])
            if not steps:
                continue

            prog = self.quest_progress.setdefault(user_id, {}).setdefault(qid, {
                "current_step": 1,
                "completed_steps": []
            })

            step_idx = prog["current_step"] - 1
            if step_idx < 0 or step_idx >= len(steps):
                continue

            step = steps[step_idx]
            if step["id"] in prog["completed_steps"]:
                continue

            # go_problem 类型：不走关键词匹配，留空等待前端解决后调 resolve_go_step
            if step.get("type") == "go_problem":
                continue

            matched = [kw for kw in step.get("keywords", []) if kw in user_lower]
            if matched:
                prog["completed_steps"].append(step["id"])
                prog["current_step"] = step["id"] + 1

                step_completions.append({
                    "qid": qid,
                    "title": quest.get("title", ""),
                    "step_id": step["id"],
                    "step_desc": step["desc"],
                    "total_steps": len(steps),
                    "completed_count": len(prog["completed_steps"]),
                })

                # 如果还有下一步，加入关键词提示
                next_step_idx = step["id"]  # step id 从1开始，next = current
                if next_step_idx < len(steps):
                    next_kws = steps[next_step_idx].get("keywords", [])
                    if next_kws:
                        hint_kw = next_kws[:3]
                        step_completions[-1]["next_hint"] = f"试试说：「{'」「'.join(hint_kw)}」"

                # 检查是否所有步骤完成
                if prog["current_step"] > len(steps):
                    reward_data = quest.get("reward_data", {})
                    # 记录完成（在移除活跃列表之前）
                    if user_id not in self.quest_completion:
                        self.quest_completion[user_id] = {}
                    self.quest_completion[user_id][qid] = {
                        "title": quest.get("title", ""),
                        "reward": quest.get("reward", ""),
                    }
                    # 持久化到 world_state.json（per-user）
                    self.memory.complete_quest(qid, user_id)
                    # 从活跃列表移除
                    self.active_quests[user_id] = [
                        q for q in self._user_quests(user_id) if q.get("qid") != qid
                    ]
                    # 清理进度
                    if qid in self.quest_progress.get(user_id, {}):
                        del self.quest_progress[user_id][qid]

                    quest_completions.append({
                        "qid": qid,
                        "title": quest.get("title", ""),
                        "reward": quest.get("reward", ""),
                        "reward_data": reward_data,
                        "next_hint": quest.get("next_hint", ""),
                        "from_npc": npc_name,
                    })

                    # 任务完成后，扫描 ALL_QUESTS 查找下一个可接任务，生成指引
                    completed_name = None
                    for qname, qdata in ALL_QUESTS.items():
                        if qdata.get("qid") == qid:
                            completed_name = qname
                            break
                    if completed_name:
                        next_hints = []
                        for qname, qdata in ALL_QUESTS.items():
                            if "trigger" not in qdata or "qid" not in qdata:
                                continue
                            if qdata.get("prerequisite") == completed_name:
                                npcs = qdata.get("npc_permission", [])
                                triggers = qdata.get("trigger", [])
                                # 只提示未触发的任务
                                tqid = qdata["qid"]
                                if not self._is_quest_completed(user_id, tqid) and not any(
                                    aq.get("qid") == tqid for aq in self._user_quests(user_id)
                                ):
                                    npc_str = "、".join(npcs)
                                    trigger_str = "「" + "」「".join(triggers[:4]) + "」"
                                    next_hints.append(f"🔮 找【{npc_str}】说 {trigger_str}")
                        if next_hints:
                            hint_text = "\n📍 **下一步：**\n" + "\n".join(next_hints)
                            quest_completions[-1]["next_hint"] = (
                                (quest_completions[-1].get("next_hint") or "") + "\n" + hint_text
                            ).strip()

                    # 关卡任务完成 → 自动推进章节
                    if qid in CHAPTER_GATES:
                        target = CHAPTER_GATES[qid]
                        prog = self.get_chapter_progress(user_id)
                        if prog["current_chapter"] < target:
                            new_prog = self.advance_chapter(user_id)
                            quest_completions[-1]["chapter_advance"] = new_prog["current_chapter"]

                    # 江湖归宿完成 → 触发结局判定
                    if qid == "jiang_hu_gui_su":
                        outcome = self._determine_ending(user_id)
                        quest_completions[-1]["outcome"] = outcome

        return step_completions, quest_completions

    # ── 章节进度系统 ─────────────────────────
    def get_chapter_progress(self, user_id: str = "default") -> dict:
        """获取用户的章节进度"""
        return self.chapter_progress.setdefault(user_id, {
            "current_chapter": 1,
            "completed_chapters": [],
            "chapter_step": 0
        })

    def advance_chapter(self, user_id: str = "default") -> dict:
        """推进到下一章，返回新章节信息"""
        prog = self.get_chapter_progress(user_id)
        current = prog["current_chapter"]
        
        # 标记当前章节为完成
        if current not in prog["completed_chapters"]:
            prog["completed_chapters"].append(current)
        
        # 推进到下一章
        prog["current_chapter"] = current + 1
        prog["chapter_step"] = 0
        
        # 持久化章节进度
        self._save_chapter_progress(user_id)
        
        return prog

    # ── 结局系统 ──
    def _determine_ending(self, user_id: str = "default") -> dict:
        """根据玩家抉择/门派/亲密度判定结局，返回结局信息"""
        if user_id in self.outcome_cache:
            return self.outcome_cache[user_id]

        import game as g
        faction = getattr(g, "faction", "")
        completed_qids = set(self.quest_completion.get(user_id, {}).keys())

        # 检查任盈盈亲密度
        ren_favor = self.memory.get_relation(user_id, "任盈盈")

        # 简化判定逻辑（OUTCOME_CONFIG中的条件依赖未实现的细粒度选择追踪）
        outcome_id = "C"  # 默认：归隐结局

        if faction == "无门派":
            outcome_id = "D"  # 独行结局
        elif "cu_xi_ye_tan" in completed_qids and ren_favor >= 40:
            outcome_id = "A"  # 促膝结局
        elif "men_pai_da_hui" in completed_qids and ren_favor >= 60:
            outcome_id = "B"  # 传道结局

        cfg = OUTCOME_CONFIG.get(outcome_id, OUTCOME_CONFIG["C"])
        result = {
            "outcome_id": outcome_id,
            "name": cfg["name"],
            "title": cfg["title"],
            "narrative": cfg["narrative"],
            "reward": cfg["reward"],
        }
        self.outcome_cache[user_id] = result
        return result

    # ── 围棋死活题步骤管理 ──
    def _get_pending_go_step(self, user_id: str = "default") -> dict:
        """检测是否有待解决的围棋死活题步骤"""
        for quest in self._user_quests(user_id):
            steps = quest.get("steps", [])
            if not steps:
                continue
            qid = quest.get("qid")
            prog = self.quest_progress.get(user_id, {}).get(qid, {})
            step_idx = prog.get("current_step", 1) - 1
            if step_idx < 0 or step_idx >= len(steps):
                continue
            step = steps[step_idx]
            if step.get("type") == "go_problem" and step["id"] not in prog.get("completed_steps", []):
                return {
                    "go_problem_id": step.get("go_problem_id", ""),
                    "quest_id": qid,
                    "quest_title": quest.get("title", ""),
                    "desc": step["desc"],
                }
        return {}

    def resolve_go_step(self, quest_id: str, user_id: str = "default") -> dict:
        """标记go_problem步骤为已完成"""
        for quest in self._user_quests(user_id):
            if quest.get("qid") != quest_id:
                continue
            steps = quest.get("steps", [])
            prog = self.quest_progress.setdefault(user_id, {}).setdefault(quest_id, {
                "current_step": 1, "completed_steps": []
            })
            step_idx = prog["current_step"] - 1
            if step_idx < 0 or step_idx >= len(steps):
                return {"error": "没有待完成的步骤"}
            step = steps[step_idx]
            if step.get("type") != "go_problem":
                return {"error": "当前步骤不是围棋死活题"}
            if step["id"] in prog["completed_steps"]:
                return {"error": "该步骤已完成"}

            # 标记完成
            prog["completed_steps"].append(step["id"])
            prog["current_step"] = step["id"] + 1

            # 检查是否所有步骤完成
            if prog["current_step"] > len(steps):
                reward_data = quest.get("reward_data", {})
                if user_id not in self.quest_completion:
                    self.quest_completion[user_id] = {}
                self.quest_completion[user_id][quest_id] = {
                    "title": quest.get("title", ""),
                    "reward": quest.get("reward", ""),
                }
                self.active_quests[user_id] = [
                    q for q in self._user_quests(user_id) if q.get("qid") != quest_id
                ]
                if quest_id in self.quest_progress.get(user_id, {}):
                    del self.quest_progress[user_id][quest_id]
                # 返回 NPC 台词供前端展示
                npc_name = quest.get("npc_permission", ["长老"])[0]
                return {
                    "completed": True,
                    "reward": quest.get("reward", ""),
                    "npc_line": f"{npc_name}微微颔首：'少侠前途无量，这局棋的妙处，日后慢慢体会吧。'",
                }

            return {"completed": False, "next_step": prog["current_step"]}
        return {"error": "任务不存在"}

    def _extract_gift(self, text: str) -> dict:
        """从LLM输出中提取礼物JSON"""
        import re
        # 匹配礼物JSON: {"gift": {"item": "物品名", "from": "NPC名"}}
        pattern = r'\{"gift":\s*\{"item":\s*"[^"]+",\s*"from":\s*"[^"]+"\}\}'
        match = re.search(pattern, text)
        if match:
            try:
                data = json.loads(match.group())
                return data.get("gift", data)  # 返回内层字典 {"item":..., "from":...}
            except Exception:
                pass
        
        # 也尝试单引号格式
        pattern2 = r"\{'gift':\s*\{'item':\s*'[^']+',\s*'from':\s*'[^']+'\}\}"
        match2 = re.search(pattern2, text)
        if match2:
            try:
                data = json.loads(match2.group().replace("'", '"'))
                return data.get("gift", data)  # 返回内层字典
            except Exception:
                pass
        
        return None

    def _strip_gift(self, text: str) -> str:
        """去掉LLM输出末尾的礼物JSON块"""
        if not text:
            return text
        stripped = text.strip()
        
        # 去掉礼物JSON块
        patterns = [
            r'\{"gift":\s*\{"item":\s*"[^"]+",\s*"from":\s*"[^"]+"\}\}',
            r"\{'gift':\s*\{'item':\s*'[^']+',\s*'from':\s*'[^']+'\}\}",
            r'\n\s*\{.*"gift".*\}\s*$',
        ]
        
        for pat in patterns:
            stripped = re.sub(pat, '', stripped, flags=re.DOTALL).strip()
        
        return stripped

    def check_chapter_advancement(self, user_input: str, npc_name: str, user_id: str = "default") -> dict:
        """检查是否应该推进章节"""
        from quest_data import CHAPTER_CONFIG
        
        prog = self.get_chapter_progress(user_id)
        current_chapter = prog["current_chapter"]
        
        if current_chapter > 6:  # 所有章节已完成
            return {"advanced": False, "completed_all": True}
        
        chapter_key = f"chapter_{current_chapter}"
        if chapter_key not in CHAPTER_CONFIG:
            return {"advanced": False, "completed_all": True}
        
        chapter_info = CHAPTER_CONFIG[chapter_key]
        
        # 检查用户输入是否匹配章节完成条件
        completion_keywords = chapter_info.get("completion_keywords", [])
        user_lower = user_input.lower()
        
        matched = [kw for kw in completion_keywords if kw.lower() in user_lower]
        
        if matched:
            # 推进章节
            new_prog = self.advance_chapter(user_id)
            return {
                "advanced": True,
                "new_chapter": new_prog["current_chapter"],
                "chapter_title": CHAPTER_CONFIG.get(f"chapter_{new_prog['current_chapter']}", {}).get("title", ""),
                "completed_chapters": new_prog["completed_chapters"]
            }
        
        return {"advanced": False, "current_chapter": current_chapter}

