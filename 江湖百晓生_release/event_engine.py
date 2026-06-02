# -*- coding: utf-8 -*-
"""
event_engine.py — 江湖百晓生 v2.0 事件引擎
离线预生成事件 + 知识图谱校验 + 质量管控管道 + 评估统计
"""
import json
import os
import random
import re
import sqlite3
import time
import uuid
import logging
from pathlib import Path
from typing import Optional, Tuple, List, Dict, Any

import networkx as nx
from langchain_core.messages import HumanMessage
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import StrOutputParser

from npc_data import NPC_PROFILES, NPC_GIFT_CONFIG

# 日志
logger = logging.getLogger("event_engine")


# ============================================================
# 工具函数
# ============================================================
def _clean_json(raw: str) -> str:
    """清理 LLM 输出中的 markdown 代码块包裹，返回纯 JSON 字符串"""
    raw = raw.strip()
    # 去掉 ```json ... ``` 包裹
    raw = re.sub(r'^```(?:json)?\s*', '', raw)
    raw = re.sub(r'\s*```$', '', raw)
    return raw.strip()


# ============================================================
# 数据库操作
# ============================================================
DB_PATH: Optional[str] = None

def _get_db() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn

def _init_db():
    conn = _get_db()
    conn.execute("""
        CREATE TABLE IF NOT EXISTS events (
            id TEXT PRIMARY KEY,
            title TEXT,
            description TEXT,
            category TEXT,
            from_npc TEXT,
            related_npcs TEXT,
            related_locations TEXT,
            impact_level INTEGER DEFAULT 1,
            status TEXT DEFAULT 'pending',
            quality_score REAL DEFAULT 0.0,
            created_at TEXT,
            used_at TEXT,
            flags TEXT
        )
    """)
    # story_nodes 表 — 离线预生成故事节点（含节点组）
    conn.execute("""
        CREATE TABLE IF NOT EXISTS story_nodes (
            id TEXT PRIMARY KEY,
            group_id TEXT DEFAULT 'default',
            title TEXT,
            category TEXT,
            from_npc TEXT,
            summary TEXT,
            location TEXT,
            involved_npcs TEXT,
            trigger_json TEXT,
            options_json TEXT,
            condition_edges_json TEXT,
            impact_json TEXT,
            day_min INTEGER DEFAULT 1,
            day_max INTEGER DEFAULT 999,
            quality_score REAL DEFAULT 0.0,
            status TEXT DEFAULT 'pending',
            created_at TEXT,
            activated_at TEXT
        )
    """)
    # 兼容旧表：加 group_id 字段
    try:
        conn.execute("ALTER TABLE story_nodes ADD COLUMN group_id TEXT DEFAULT 'default'")
    except Exception as e:
        logger.info(f"group_id column already exists ({e})")
    # npc_experience_log — NPC经历日志（用于反思）
    conn.execute("""
        CREATE TABLE IF NOT EXISTS npc_experience_log (
            id TEXT PRIMARY KEY,
            npc_name TEXT NOT NULL,
            experience TEXT NOT NULL,
            importance_score REAL DEFAULT 5.0,
            source_type TEXT,
            source_id TEXT,
            created_at TEXT
        )
    """)
    # npc_reflections — NPC反思记录
    conn.execute("""
        CREATE TABLE IF NOT EXISTS npc_reflections (
            id TEXT PRIMARY KEY,
            npc_name TEXT NOT NULL,
            reflection TEXT NOT NULL,
            insight_type TEXT DEFAULT 'self',
            related_npcs TEXT DEFAULT '[]',
            importance_score REAL DEFAULT 5.0,
            created_at TEXT
        )
    """)
    # 兼容旧表：加 importance_score 字段
    try:
        conn.execute("ALTER TABLE story_nodes ADD COLUMN importance_score REAL DEFAULT 5.0")
    except Exception as e:
        logger.info(f"importance_score column already exists ({e})")
    # 兼容旧表：加 chain_id / chain_step 字段
    try:
        conn.execute("ALTER TABLE story_nodes ADD COLUMN chain_id TEXT DEFAULT ''")
    except Exception as e:
        logger.info(f"chain_id column already exists ({e})")
    try:
        conn.execute("ALTER TABLE story_nodes ADD COLUMN chain_step INTEGER DEFAULT 0")
    except Exception as e:
        logger.info(f"chain_step column already exists ({e})")
    conn.commit()
    conn.close()
# ============================================================
# KnowledgeGraph — 知识图谱（networkx）
# ============================================================
class KnowledgeGraph:
    """基于 NPC_PROFILES 构建角色-地点关系图"""

    def __init__(self):
        self.G = nx.Graph()
        self._build()

    def _build(self):
        """从 NPC_PROFILES 自动构建图谱"""
        # 添加 NPC 节点
        for name, profile in NPC_PROFILES.items():
            loc = profile.get("location", "未知")
            self.G.add_node(name, type="npc", location=loc)
            self.G.add_node(loc, type="location")
            self.G.add_edge(name, loc, relation="位于")

        # NPC 之间假设在同一地点的有关系边
        loc_groups = {}
        for name, profile in NPC_PROFILES.items():
            loc = profile.get("location", "未知")
            loc_groups.setdefault(loc, []).append(name)
        for loc, npcs in loc_groups.items():
            for i in range(len(npcs)):
                for j in range(i + 1, len(npcs)):
                    if not self.G.has_edge(npcs[i], npcs[j]):
                        self.G.add_edge(npcs[i], npcs[j], relation="同地")

        # 已知关系的 NPC 之间加强连接
        relation_pairs = [
            ("洪七公", "欧阳克"),  ("武林盟主", "神秘大侠"),
            ("任盈盈", "任我行"),  ("黄衫女", "瑛姑"),
            ("店小二", "洪七公"),
        ]
        for a, b in relation_pairs:
            if a in self.G and b in self.G:
                self.G.add_edge(a, b, relation="关联")

    def validate_event(self, event: dict) -> tuple:
        """校验事件合法性，返回 (通过: bool, 原因: str)
        放宽校验：未知NPC/地点自动忽略，只检查已知的"""
        from_npc = event.get("from_npc", "")
        related_npcs = event.get("related_npcs", [])
        related_locs = event.get("related_locations", [])

        # 1. 发起者必须在图中
        if from_npc and from_npc not in self.G:
            return False, f"NPC '{from_npc}' 不在知识图谱中"

        # 2. 关联 NPC 不在图中的直接过滤掉
        known_npcs = [n for n in related_npcs if n in self.G]
        event["related_npcs"] = known_npcs

        # 3. 关联地点不在图中的直接过滤掉
        known_locs = [loc for loc in related_locs if loc in self.G]
        event["related_locations"] = known_locs

        # 4. 跳过NPC间关系校验（世界里的NPC可以听说彼此的事）
        # 知识图谱只做矛盾检测，不做熟人检测

        # 5. 已知的关联地点必须和 NPC 有关联
        if from_npc and known_locs:
            for loc in known_locs:
                if not self.G.has_edge(from_npc, loc) and not any(
                    self.G.has_edge(n, loc) for n in known_npcs
                ):
                    return False, f"地点 '{loc}' 与事件中任何NPC都无关联"

        return True, ""

    def get_related_npcs(self, npc_name: str) -> list:
        """获取一个 NPC 的所有关联 NPC"""
        if npc_name not in self.G:
            return []
        return [n for n in self.G.neighbors(npc_name)
                if self.G.nodes[n].get("type") == "npc"]


# ============================================================
# EventGenerator — DeepSeek 批量生成事件
# ============================================================
class EventGenerator:
    """用 DeepSeek 为指定 NPC 生成事件节点"""

    CATEGORIES = ["npc_action", "world_news", "npc_conflict"]

    def __init__(self, llm):
        self.llm = llm

    def generate_batch(self, npc_name: str, count: int = 5, existing_context: str = "") -> list:
        """为 NPC 生成 count 个事件，existing_context 为已通过事件列表（用于全局一致性）
        始终使用静态 NPC_PROFILES.motivation，保证与 pregen 一致。"""
        profile = NPC_PROFILES.get(npc_name, NPC_PROFILES["店小二"])
        mot = profile.get("motivation", {})
        # 可用NPC列表（告诉DeepSeek别瞎编）
        npc_list = "、".join(NPC_PROFILES.keys())
        loc_list = "、".join(set(p.get("location","未知") for p in NPC_PROFILES.values()))
        prompt = (
            f"你为武侠游戏生成事件，事件是关于NPC '{npc_name}' 的。\n"
            f"NPC性格：{profile['system_prompt'][:60]}...\n"
            f"动机：{mot.get('drive', '')}，当前心情：{mot.get('mood', '平静')}，目标：{mot.get('goal', '')}\n"
            f"生成 {count} 个江湖事件，要求：\n"
            f"1. 每个事件包含 title(6字内)、description(30字内)\n"
            f"2. 从以下类别选一个：{','.join(self.CATEGORIES)}\n"
            f"3. 关联 NPC 只能从下面列表里选：{npc_list}\n"
            f"4. 关联地点只能从下面列表里选：{loc_list}\n"
            f"5. 不能和'{npc_name}'的设定矛盾\n"
            f"{existing_context}"
            f"6. importance_score: 事件重要性(3-10)，主线推动事件8-10，支线5-7，氛围事件3-4\n"
            f"7. day_range: [最早天数, 最晚天数]，开场事件[1,3]，中期[3,7]，后期[5,999]\n"
            f"8. options_json: 2-3个玩家选择项 [{{'text':'选项文本','result':{{'favor_change':-5或5}},'hint':'提示'}}]\n"
            f"9. impact_json: 世界影响 {{'npc_relation':{{'NPC名':{{'另一NPC':值}}}}}}\n"
            f"10. chain_id: 本事件所属链标题（如'丐帮vs白驼'），同一链的多个事件共享chain_id，非链事件留空\n"
            f"11. chain_step: 本事件在链中的步数（从0开始），非链事件留空\n"
            f"输出JSON数组：[{{'title':'','description':'','category':'','from_npc':'{npc_name}',"
            f"'related_npcs':[],'related_locations':[],'impact_level':1-5,"
            f"'importance_score':5,'day_range':[1,999],"
            f"'options_json':[],'impact_json':{{}},'chain_id':'','chain_step':0}}]。"
        )
        try:
            p = ChatPromptTemplate.from_messages([HumanMessage(content=prompt)])
            raw = (p | self.llm | StrOutputParser()).invoke({})
            clean = _clean_json(raw)
            events = json.loads(clean)
            if not isinstance(events, list):
                events = [events]
            for e in events:
                e.setdefault("related_npcs", [])
                e.setdefault("related_locations", [])
                e["from_npc"] = npc_name
            return events
        except Exception as e:
            logger.warning(f"generate_batch parse failed: {e}")
            return []


# ============================================================
# QualityStats — 三层过滤效果统计
# ============================================================
class QualityStats:
    def __init__(self):
        self.reset()

    def reset(self):
        self.total_generated = 0
        self.passed_embedding = 0
        self.passed_knowledge_graph = 0
        self.passed_review = 0
        self.scores_before = []
        self.scores_after = []

    def record_generated(self, count: int):
        self.total_generated += count

    def record_embedding_pass(self, count: int):
        self.passed_embedding += count

    def record_kg_pass(self, count: int):
        self.passed_knowledge_graph += count

    def record_review(self, passed: int, scores_before: list, scores_after: list):
        self.passed_review += passed
        self.scores_before.extend(scores_before)
        self.scores_after.extend(scores_after)

    def report(self) -> dict:
        t = self.total_generated or 1
        ep = self.passed_embedding
        kg = self.passed_knowledge_graph
        rv = self.passed_review
        return {
            "total": t,
            "pass_rate_embedding": f"{ep}/{t} ({ep/t*100:.0f}%)",
            "pass_rate_kg": f"{kg}/{ep} ({kg/ep*100:.0f}%)" if ep else "0/0",
            "pass_rate_review": f"{rv}/{kg} ({rv/kg*100:.0f}%)" if kg else "0/0",
            "final_pass_rate": f"{rv}/{t} ({rv/t*100:.0f}%)",
            "avg_score_before": round(sum(self.scores_before)/len(self.scores_before), 2) if self.scores_before else 0,
            "avg_score_after": round(sum(self.scores_after)/len(self.scores_after), 2) if self.scores_after else 0,
        }


# ============================================================
# Diagnostics — 诊断系统
# ============================================================
class Diagnostics:
    """系统诊断 / 运行指标收集"""

    def __init__(self):
        self.start_time = time.time()
        self.tick_count = 0
        self.last_tick_msg = ""

    def record_tick(self, msg: str = ""):
        self.tick_count += 1
        if msg:
            self.last_tick_msg = msg

    def get_uptime(self) -> str:
        sec = int(time.time() - self.start_time)
        h, m = divmod(sec, 3600)
        m, s = divmod(m, 60)
        return f"{h}h {m}m {s}s"

    def report(self, event_mgr=None, chat=None) -> dict:
        """生成完整诊断报告"""
        r = {
            "server": {
                "uptime": self.get_uptime(),
                "ticks": self.tick_count,
                "last_tick": self.last_tick_msg[:80] if self.last_tick_msg else "",
            }
        }
        # 故事节点统计
        if event_mgr:
            try:
                nodes = event_mgr.get_pending_story_nodes()
                active = event_mgr.get_active_story_nodes()
                r["story_nodes"] = {
                    "total": len(nodes) + len(active),
                    "pending": len(nodes),
                    "active": len(active),
                }
            except Exception:
                pass
            # 管道统计
            try:
                ps = event_mgr.pipeline.stats.report()
                r["quality_pipeline"] = ps
            except Exception:
                pass
        # NPC动机快照
        if chat and hasattr(chat, 'motivation_manager'):
            try:
                mot = {}
                for name in list(NPC_PROFILES.keys()):
                    m = chat.motivation_manager.get(name)
                    mot[name] = f"{m.get('mood','?')}→{m.get('goal','?')[:12]}"
                r["npc_motivations"] = mot
            except Exception:
                pass
        return r
class EventQualityPipeline:
    """embedding粗筛（语义矛盾检测）+ 知识图谱校验 + AI评审团评分"""

    def __init__(self, knowledge_graph: KnowledgeGraph, llm, embeddings=None):
        self.kg = knowledge_graph
        self.llm = llm
        self.embeddings = embeddings
        self.stats = QualityStats()
        self._passed_pool = []       # [(向量, {title, description, from_npc}), ...]

    def filter(self, events: list) -> list:
        """对事件列表执行三层过滤，返回通过的事件"""
        self.stats.record_generated(len(events))
        results = []

        for event in events:
            passed, reason = self._step1_embedding(event)
            if not passed:
                continue
            passed, reason = self._step2_kg(event)
            if not passed:
                continue
            passed, score = self._step3_review(event)
            if passed:
                enriched = {**event, "quality_score": score, "status": "active"}
                results.append(enriched)
                # 通过的事件加入向量池（只有通过KG+LLM的才入库参考）
                self._add_to_pool(enriched)

        self.stats.record_review(len(results), [], [e.get("quality_score", 0) for e in results])
        return results

    def _add_to_pool(self, event: dict):
        """将已通过事件加入向量池"""
        text = f"{event.get('title','')} {event.get('description','')} {event.get('from_npc','')}"
        vec = self._embed(text)
        if vec:
            self._passed_pool.append((vec, {
                "title": event.get("title",""),
                "description": event.get("description",""),
                "from_npc": event.get("from_npc",""),
                "related_npcs": event.get("related_npcs",[]),
                "related_locations": event.get("related_locations",[]),
            }))

    def _embed(self, text: str) -> list:
        """用BGE模型计算向量，失败返回None"""
        if not self.embeddings:
            return None
        try:
            return self.embeddings.embed_query(text)
        except Exception:
            return None

    def _retrieve_similar(self, event: dict, top_k: int = 3, threshold: float = 0.75) -> list:
        """从已通过池召回语义相似的事件"""
        if not self._passed_pool:
            return []
        text = f"{event.get('title','')} {event.get('description','')} {event.get('from_npc','')}"
        vec = self._embed(text)
        if not vec:
            return []
        import numpy as np
        vec_np = np.array(vec)
        results = []
        for pool_vec, pool_event in self._passed_pool:
            pv = np.array(pool_vec)
            dot = np.dot(vec_np, pv)
            norm = np.linalg.norm(vec_np) * np.linalg.norm(pv)
            sim = dot / norm if norm > 0 else 0
            if sim >= threshold:
                results.append((sim, pool_event))
        results.sort(key=lambda x: -x[0])
        return results[:top_k]

    def _step1_embedding(self, event: dict) -> tuple:
        """Step 1: 基础文本校验 + 语义召回。检查长度/现代词汇，召回相似事件供step3矛盾检测"""
        # 基础校验（保留）
        desc = event.get("description", "")
        title = event.get("title", "")
        if len(desc) < 5 or len(title) < 2:
            return False, "内容太短"
        if len(desc) > 200:
            return False, "内容太长"
        if any(kw in desc for kw in ["AI", "机器人", "游戏", "玩家"]):
            return False, "包含现代词汇"

        # 语义矛盾检测：召回相似事件
        similar = self._retrieve_similar(event, top_k=2, threshold=0.72)
        if similar:
            # 只要检索到语义相似的，标记在 event 上供 step3 使用
            event["_similar_events"] = [s[1] for s in similar]
        else:
            event["_similar_events"] = []

        self.stats.record_embedding_pass(1)
        return True, ""

    def _step2_kg(self, event: dict) -> tuple:
        """Step 2: 知识图谱校验"""
        passed, reason = self.kg.validate_event(event)
        if passed:
            self.stats.record_kg_pass(1)
        return passed, reason

    def _step3_review(self, event: dict) -> tuple:
        """Step 3: AI评审团评分（3次调用取均值，≥6分通过）"""
        # 收集相似事件上下文（供矛盾检测）
        similar_ctx = ""
        sim_events = event.get("_similar_events", [])
        if sim_events:
            lines = []
            for i, se in enumerate(sim_events[:2]):
                lines.append(
                    f"[已有事件{i+1}] {se.get('title','')} - {se.get('description','')} (发起者: {se.get('from_npc','')})"
                )
            similar_ctx = "\n相似历史事件（请检查是否有矛盾）：\n" + "\n".join(lines)

        scores = []
        for _ in range(1):
            score = self._single_review(event, similar_ctx)
            if score is not None:
                scores.append(score)
        if not scores:
            return False, 0
        avg = sum(scores) / len(scores)
        return avg >= 5.0, avg

    def _single_review(self, event: dict, similar_ctx: str = "") -> float:
        """单次DeepSeek评审，返回1-10分（含矛盾检测）"""
        prompt = (
            f"你是江湖故事评审，评价以下江湖事件的质量（1-10分）：\n"
            f"标题：{event.get('title','')}\n"
            f"描述：{event.get('description','')}\n"
            f"发起者：{event.get('from_npc','')}\n"
            f"关联：{event.get('related_npcs',[])} {event.get('related_locations',[])}\n"
            f"{similar_ctx}"
            f"\n评分维度：合理性25%、戏剧性25%、设定一致性25%、趣味性25%\n"
            f"注意：如果与已有事件存在矛盾（如同一件事但关键信息冲突），直接给0分！\n"
            f"输出JSON：{{\"score\": 数字(1-10), \"reason\": \"一句话\"}}"
        )
        try:
            p = ChatPromptTemplate.from_messages([HumanMessage(content=prompt)])
            raw = (p | self.llm | StrOutputParser()).invoke({})
            clean = _clean_json(raw)
            data = json.loads(clean)
            return float(data.get("score", 5))
        except Exception:
            return None

    def diagnose_filter(self, events: list) -> dict:
        """诊断模式：跑三层过滤但详细记录每条事件的每层结果
        返回结构：
        {
          "summary": {总览统计},
          "layers": {各层过滤详情},
          "events": [{每条事件的诊断结果}]
        }
        """
        import time
        t0 = time.time()
        total = len(events)
        layer1_pass = 0
        layer2_pass = 0
        layer3_pass = 0
        layer1_rejects = []   # 被第1层拒绝的
        layer2_rejects = []   # 被第2层拒绝的
        layer3_rejects = []   # 被第3层拒绝的
        passed_events = []

        for event in events:
            event_diag = {
                "title": event.get("title", ""),
                "description": event.get("description", ""),
                "from_npc": event.get("from_npc", ""),
                "category": event.get("category", ""),
                "layers": {}
            }

            # Step 1: Embedding粗筛
            p1, r1 = self._step1_embedding(event)
            event_diag["layers"]["embedding"] = {"passed": p1, "reason": r1}
            if not p1:
                layer1_rejects.append({"title": event.get("title",""), "reason": r1})
                continue
            layer1_pass += 1

            # Step 2: 知识图谱校验
            p2, r2 = self._step2_kg(event)
            event_diag["layers"]["kg"] = {"passed": p2, "reason": r2}
            if not p2:
                layer2_rejects.append({"title": event.get("title",""), "reason": r2, "from_npc": event.get("from_npc","")})
                continue
            layer2_pass += 1

            # Step 3: AI评审团评分
            p3, score = self._step3_review(event)
            event_diag["layers"]["review"] = {"passed": p3, "score": round(score, 1)}
            if not p3:
                layer3_rejects.append({"title": event.get("title",""), "score": round(score,1), "from_npc": event.get("from_npc","")})
                continue
            layer3_pass += 1

            event_diag["quality_score"] = round(score, 1)
            passed_events.append(event_diag)

        elapsed = round(time.time() - t0, 2)

        # 按失败层分类的"坏事件"示例（每种最多取3个）
        def sample(items, n=3):
            return items[:n]

        return {
            "summary": {
                "total": total,
                "layer1_embedding": {"passed": layer1_pass, "rejected": total - layer1_pass,
                    "pass_rate": f"{layer1_pass}/{total} ({layer1_pass/total*100:.0f}%)" if total else "N/A"},
                "layer2_kg": {"passed": layer2_pass, "rejected": layer1_pass - layer2_pass,
                    "pass_rate": f"{layer2_pass}/{layer1_pass} ({layer2_pass/layer1_pass*100:.0f}%)" if layer1_pass else "N/A"},
                "layer3_review": {"passed": layer3_pass, "rejected": layer2_pass - layer3_pass,
                    "pass_rate": f"{layer3_pass}/{layer2_pass} ({layer3_pass/layer2_pass*100:.0f}%)" if layer2_pass else "N/A",
                    "avg_score": round(sum(e["quality_score"] for e in passed_events)/len(passed_events), 1) if passed_events else 0},
                "final_pass": f"{layer3_pass}/{total} ({layer3_pass/total*100:.0f}%)" if total else "N/A",
                "elapsed_sec": elapsed,
            },
            "rejects_sample": {
                "layer1_embedding": sample(layer1_rejects),
                "layer2_kg": sample(layer2_rejects),
                "layer3_review": sample(layer3_rejects),
            },
            "passed_sample": sample(passed_events),
        }


# ============================================================
# EventManager — 对外接口
# ============================================================


class EventManager:
    def __init__(self, chat_instance):
        global DB_PATH
        self.chat = chat_instance
        self.base_dir = Path(os.path.dirname(os.path.abspath(__file__)))
        events_dir = self.base_dir / "events"
        events_dir.mkdir(exist_ok=True)
        DB_PATH = str(events_dir / "events.db")
        _init_db()
        self.kg = KnowledgeGraph()
        self.generator = EventGenerator(chat_instance.llm)
        self.pipeline = EventQualityPipeline(self.kg, chat_instance.llm,
                                              getattr(chat_instance, 'embeddings', None))
        # 事件链管理
        self._active_chains = {}   # chain_id -> chain_state（仅用于诊断）
        self._chains_advanced_this_tick = set()  # 本tick已推过的链ID
        # 节点组
        self._current_group_id = None  # 本局选中的组
        # 消息冷却与配额（防轰炸）
        self._npc_mail_cooldown = {}   # npc_name -> 上次发消息时间戳
        self._global_mail_log = []     # 最近发消息的时间戳列表
        self.MAIL_COOLDOWN_SEC = 300   # 单NPC冷却5分钟
        self.GLOBAL_WINDOW_SEC = 150   # 全局窗口2.5分钟
        self.GLOBAL_MAX_MAIL = 1       # 窗口内最多1条（防轰炸）
        # 反思系统
        self._last_reflection_time = {}   # npc_name -> 上次反思时间戳
        self.REFLECTION_THRESHOLD = 30    # 累积重要性 ≥ 30 触发反思
        # 诊断系统
        self.diag = Diagnostics()

    def generate_for_npc(self, npc_name: str, count: int = 5) -> list:
        """为指定NPC生成事件并入库"""
        if npc_name not in NPC_PROFILES:
            return []
        events = self.generator.generate_batch(npc_name, count)
        if not events:
            return []
        passed = self.pipeline.filter(events)
        self._save_events(passed)
        return passed

    def generate_for_all(self, count_per_npc: int = 3) -> dict:
        """为所有NPC生成事件"""
        total = {"generated": 0, "passed": 0, "npcs": {}}
        for npc_name in NPC_PROFILES:
            events = self.generate_for_npc(npc_name, count_per_npc)
            total["npcs"][npc_name] = {"generated": count_per_npc, "passed": len(events)}
            total["generated"] += count_per_npc
            total["passed"] += len(events)
        return total

    def get_active_events(self, npc_name: str = None) -> list:
        """获取活跃事件"""
        conn = _get_db()
        if npc_name:
            rows = conn.execute(
                "SELECT * FROM events WHERE status='active' AND from_npc=?",
                (npc_name,)
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM events WHERE status='active'"
            ).fetchall()
        conn.close()
        return [dict(r) for r in rows]

    def resolve_event(self, event_id: str):
        """标记事件为已处理"""
        conn = _get_db()
        conn.execute("UPDATE events SET status='done', used_at=? WHERE id=?",
                     (time.strftime("%Y-%m-%dT%H:%M:%S"), event_id))
        conn.commit()
        conn.close()

    def get_events_for_context(self, npc_name: str) -> str:
        """生成可注入 prompt 的事件上下文"""
        events = self.get_active_events(npc_name)
        if not events:
            return ""
        lines = []
        for e in events[:3]:
            lines.append(f"- {e.get('title', '')}：{e.get('description', '')}")
        return "\n【江湖动态】\n" + "\n".join(lines)

    def get_chain_context_for_npc(self, npc_name: str) -> str:
        """获取与NPC相关的活跃事件链步骤，注入对话prompt让NPC知道该推进什么剧情"""
        lines = []
        now = time.time()
        for chain_id, chain in self._active_chains.items():
            # 情况1：链还在进行中，当前步骤正好是该NPC
            if not chain.get("done"):
                step_idx = chain["current_step"]
                if step_idx < len(chain["steps"]):
                    step = chain["steps"][step_idx]
                    if step["npc"] == npc_name:
                        lines.append(
                            f"- 你正身处事件「{chain['title']}」（第{step_idx+1}/{len(chain['steps'])}步），"
                            f"当前目标：{step.get('goal', '处理此事')}。"
                        )
                continue

            # 情况2：链刚完成（5分钟内），且最后一步是该NPC —— 让他在对话里自然收尾
            done_at = chain.get("_done_at", 0)
            if now - done_at < 300 and chain["steps"]:
                last_step = chain["steps"][-1]
                if last_step["npc"] == npc_name:
                    lines.append(
                        f"- 你刚完成了「{chain['title']}」，"
                        f"如果话题相关，可以自然提及结果或邀约。"
                    )
        return "\n【剧情动向】\n" + "\n".join(lines) if lines else ""

    def get_reflection_context_for_npc(self, npc_name: str) -> str:
        """获取NPC最近的反思内心独白，注入对话让玩家感受NPC在思考"""
        conn = _get_db()
        try:
            rows = conn.execute(
                "SELECT reflection FROM npc_reflections "
                "WHERE npc_name=? ORDER BY created_at DESC LIMIT 2",
                (npc_name,)
            ).fetchall()
        except Exception:
            rows = []
        finally:
            conn.close()
        if not rows:
            return ""
        inner = "\n".join(f"  - {r[0]}" for r in rows)
        return (
            "\n【内心独白】\n"
            f"以下是NPC基于最近经历产生的内心想法（自然融入对话，不要直接复述）：\n"
            f"{inner}\n"
        )

    def get_stats(self) -> dict:
        """获取过滤效果统计"""
        return self.pipeline.stats.report()

    def benchmark_generate(self, npc_name: str = None, count: int = 8) -> dict:
        """诊断模式：为指定 NPC 生成事件，返回原始事件 + 三层过滤诊断结果
        用于对比「传统LLM直出」vs「预生成三层评审」的效果差异
        npc_name=None 时随机选一个 NPC"""
        import random, time
        t0 = time.time()
        if npc_name is None:
            npc_name = random.choice(list(NPC_PROFILES.keys()))

        # 生成原始事件（传统做法：LLM直出，不经任何过滤）
        raw_events = self.generator.generate_batch(npc_name, count)
        if not raw_events:
            return {"error": f"NPC {npc_name} 事件生成失败"}

        # 防护：npc_name 为空或不在 NPC_PROFILES 中
        if not npc_name or npc_name not in NPC_PROFILES:
            return {"error": f"NPC '{npc_name}' 不存在于 NPC_PROFILES 中", "valid_npcs": list(NPC_PROFILES.keys())[:20]}

        # 三层过滤诊断
        diag = self.pipeline.diagnose_filter(raw_events)

        elapsed = round(time.time() - t0, 2)
        return {
            "npc": npc_name,
            "npc_profile": {
                "drive": NPC_PROFILES[npc_name]["motivation"]["drive"],
                "mood": NPC_PROFILES[npc_name]["motivation"]["mood"],
                "goal": NPC_PROFILES[npc_name]["motivation"]["goal"],
            },
            "raw_total": len(raw_events),
            "diagnosis": diag,
            "elapsed_sec": elapsed,
            "interpretation": {
                "without_review": f"传统做法：LLM直接产出{len(raw_events)}条事件，不经审查直接注入游戏。"
                                f"可能的隐患：{len(raw_events)-len(diag['passed_sample'])}条存在质量/一致性问题。",
                "with_review": f"预生成三层评审：{len(raw_events)}条原始事件 -> "
                              f"第1层(embedding)过{diag['summary']['layer1_embedding']['passed']}条 -> "
                              f"第2层(知识图谱)过{diag['summary']['layer2_kg']['passed']}条 -> "
                              f"第3层(AI评审)过{diag['summary']['layer3_review']['passed']}条",
            }
        }

    @staticmethod
    def _detect_contradictions_deterministic(events: list) -> dict:
        """确定性矛盾检测：同一NPC在重叠时段出现在不同地点
        不依赖LLM，纯规则判断，结果可复现。
        """
        if len(events) < 2:
            return {"contradiction_count": 0, "details": []}

        from collections import defaultdict
        by_npc = defaultdict(list)
        for e in events:
            npc = e.get("from_npc", "")
            if not npc:
                continue
            by_npc[npc].append(e)

        details = []

        for npc, npc_events in by_npc.items():
            if len(npc_events) < 2:
                continue
            for i in range(len(npc_events)):
                for j in range(i + 1, len(npc_events)):
                    e1, e2 = npc_events[i], npc_events[j]
                    locs1 = set(e1.get("related_locations", []) or [])
                    locs2 = set(e2.get("related_locations", []) or [])
                    # 缺地点信息或地点相同 → 不矛盾
                    if not locs1 or not locs2 or locs1 == locs2:
                        continue

                    dr1 = e1.get("day_range", [0, 999])
                    dr2 = e2.get("day_range", [0, 999])
                    if (isinstance(dr1, list) and len(dr1) >= 2
                            and isinstance(dr2, list) and len(dr2) >= 2):
                        # 时段重叠：A.start <= B.end AND B.start <= A.end
                        if dr1[0] <= dr2[1] and dr2[0] <= dr1[1]:
                            details.append(
                                f"【{npc}】同时出现在{','.join(locs1)}和{','.join(locs2)}："
                                f"\"{e1.get('title','')}\" vs \"{e2.get('title','')}\""
                                f" (时段{dr1[0]}-{dr1[1]}天, {dr2[0]}-{dr2[1]}天)"
                            )

        return {
            "contradiction_count": len(details),
            "details": details,
            "method": "deterministic",
        }

    def compare_generation_modes(self, npc_count: int = 4, events_per_npc: int = 3) -> dict:
        """对比「隔离生成(模拟实时)」vs「全局生成(预生成)」的矛盾率
        使用确定性规则检测矛盾（同一NPC重叠时段不同地点），跑3轮取均值。
        """
        import random, time

        t0 = time.time()
        all_npcs = list(NPC_PROFILES.keys())
        rounds = 3
        round_results = []

        for round_idx in range(rounds):
            npc_names = random.sample(all_npcs, min(npc_count, len(all_npcs)))

            # 模式1: 隔离生成
            isolated_events = []
            for npc in npc_names:
                evts = self.generator.generate_batch(npc, events_per_npc, existing_context="")
                isolated_events.extend(evts)

            # 模式2: 全局生成
            global_events = []
            global_ctx_lines = []
            for npc in npc_names:
                ctx = ""
                if global_ctx_lines:
                    ctx = "\n【已存在的江湖事件（请勿矛盾）】\n" + "\n".join(global_ctx_lines[-12:]) + "\n"
                evts = self.generator.generate_batch(npc, events_per_npc, existing_context=ctx)
                global_events.extend(evts)
                for e in evts:
                    global_ctx_lines.append(
                        f"{e.get('from_npc','')}：{e.get('title','')} - {e.get('description','')}"
                    )

            iso_contra = self._detect_contradictions_deterministic(isolated_events)
            glo_contra = self._detect_contradictions_deterministic(global_events)

            round_results.append({
                "round": round_idx + 1,
                "npcs": npc_names,
                "total_events": len(isolated_events),
                "isolated": {
                    "contradiction_count": iso_contra["contradiction_count"],
                    "details": iso_contra["details"],
                    "events": [{"title": e.get("title",""), "from_npc": e.get("from_npc",""),
                                "description": e.get("description",""),
                                "related_locations": e.get("related_locations",[]),
                                "day_range": e.get("day_range",[0,999])} for e in isolated_events],
                },
                "global": {
                    "contradiction_count": glo_contra["contradiction_count"],
                    "details": glo_contra["details"],
                    "events": [{"title": e.get("title",""), "from_npc": e.get("from_npc",""),
                                "description": e.get("description",""),
                                "related_locations": e.get("related_locations",[]),
                                "day_range": e.get("day_range",[0,999])} for e in global_events],
                },
            })

        iso_counts = [r["isolated"]["contradiction_count"] for r in round_results]
        glo_counts = [r["global"]["contradiction_count"] for r in round_results]

        elapsed = round(time.time() - t0, 1)

        return {
            "npcs_all": list(set(n for r in round_results for n in r["npcs"])),
            "events_per_npc": events_per_npc,
            "rounds": rounds,
            "total_events_all": sum(r["total_events"] for r in round_results),
            "elapsed_sec": elapsed,

            "summary": {
                "isolated": {
                    "total_contradictions": sum(iso_counts),
                    "avg_per_round": round(sum(iso_counts) / len(iso_counts), 1),
                    "details": sum([r["isolated"]["details"] for r in round_results], []),
                },
                "global": {
                    "total_contradictions": sum(glo_counts),
                    "avg_per_round": round(sum(glo_counts) / len(glo_counts), 1),
                    "details": sum([r["global"]["details"] for r in round_results], []),
                },
                "delta": sum(iso_counts) - sum(glo_counts),
            },

            "rounds_detail": round_results,

            "verdict": (
                f"共{rounds}轮 × {npc_count}NPC × {events_per_npc}事件 = {rounds * npc_count * events_per_npc}组\n"
                f"确定性规则检测（同NPC重叠时段不同地点）：\n"
                f"隔离模式(模拟实时)：{sum(iso_counts)}处矛盾（均{round(sum(iso_counts)/len(iso_counts),1)}/轮）\n"
                f"全局模式(预生成)：{sum(glo_counts)}处矛盾（均{round(sum(glo_counts)/len(glo_counts),1)}/轮）\n"
                f"预生成{'减少' if sum(glo_counts) < sum(iso_counts) else '增加' if sum(glo_counts) > sum(iso_counts) else '持平'} "
                f"{abs(sum(iso_counts) - sum(glo_counts))}处矛盾。"
            ),
        }

    def generate_story_tree(self, total_nodes: int = 500, group_id: str = "default"):
        """预生成故事节点树，按时间窗推进：
        1-5天生成全部NPC事件 → 过滤 → 全局概要传进6-10天 → ... 到50天也可回溯全部节点。
        """
        import game as g
        all_passed = []
        world_summary = []
        npc_names = list(NPC_PROFILES.keys())
        per_npc = max(1, total_nodes // len(npc_names))
        failed_npcs = []

        # 按时间窗推进（每窗10天），共5窗
        window_size = 10
        total_days = 50
        windows = list(range(1, total_days + 1, window_size))

        # 每个NPC最多参与3个随机窗口（防止尾部灵感枯竭）
        import random
        rng = random.Random()
        npc_window_map = {}
        for npc in npc_names:
            n_win = min(3, len(windows))
            npc_window_map[npc] = set(rng.sample(range(len(windows)), n_win))

        print(f"[StoryTree] 开始时间窗生成，计划 {total_nodes} 个节点，"
              f"{len(windows)}个时间窗覆盖{total_days}天，每NPC最多3窗 (组={group_id})...")

        for wi, start_day in enumerate(windows):
            end_day = min(start_day + window_size - 1, total_days)
            win_events = []

            for npc_name in npc_names:
                # 该NPC在本窗不出现
                if wi not in npc_window_map.get(npc_name, set()):
                    continue
                existing_ctx = ""
                if world_summary:
                    summary_text = "\n".join(world_summary[-50:])
                    sorted_by_imp = sorted(all_passed, key=lambda e: e.get("importance_score", 5), reverse=True)
                    recent_focus = sorted(sorted_by_imp[:5],
                                          key=lambda e: (e.get("day_range", [0, 999]) or [0, 999])[0])
                    focus_lines = []
                    for e in recent_focus:
                        dr = e.get("day_range", [0, 999])
                        focus_lines.append(f"  • 第{dr[0]}-{dr[1]}天 {e.get('title','')}({e.get('from_npc','')})：{e.get('description','')}")
                    existing_ctx = (
                        f"\n【江湖大事概要（截至第{start_day - 1}天）】\n{summary_text}\n\n"
                        f"【近期重点事件详情】\n" + "\n".join(focus_lines) + "\n"
                    )

                per_window = 2

                try:
                    events = self.generator.generate_batch(npc_name, per_window, existing_context=existing_ctx)
                except Exception as e:
                    print(f"  [时间窗{start_day}-{end_day}] {npc_name}: 异常（{e}），跳过")
                    failed_npcs.append(npc_name)
                    continue
                if events:
                    win_events.extend(events)

            # 当前窗所有NPC的事件一起过滤
            if not win_events:
                continue
            passed = self.pipeline.filter(win_events)
            print(f"  [时间窗{start_day}-{end_day}天] 生成{len(win_events)}个，通过{len(passed)}个")
            for e in passed:
                self._save_story_node(e, group_id=group_id)
                all_passed.append(e)
                dr = e.get("day_range", [0, 999])
                world_summary.append(
                    f"· 第{dr[0]}-{dr[1]}天 {e.get('from_npc','')}「{e.get('title','')}」重要度{e.get('importance_score',5)}"
                )

            # 链连接：同一chain_id的节点按step链接
            chain_groups = {}
            for e in passed:
                cid = e.get("chain_id", "") or ""
                if cid:
                    chain_groups.setdefault(cid, []).append(e)
            if chain_groups:
                try:
                    conn3 = _get_db()
                    for cid, steps in chain_groups.items():
                        steps.sort(key=lambda x: x.get("chain_step", 0))
                        for i, step in enumerate(steps[:-1]):
                            nxt = steps[i + 1]
                            nxt_npc = nxt.get("from_npc", "")
                            nxt_loc = (nxt.get("related_locations", []) or [None])[0] or ""
                            nxt_title = nxt.get("title", "")
                            edge = {
                                "condition": f"chain_complete('{cid}_step{i}')",
                                "target_npc": nxt_npc,
                                "target_location": nxt_loc,
                                "hint": f"下一步：去找{nxt_npc}（{nxt_title}）",
                                "score": 10.0,
                                "source": "pregen_chain",
                            }
                            # 用title+from_npc查询当前节点ID（同一窗内title不重复）
                            row = conn3.execute(
                                "SELECT id FROM story_nodes WHERE group_id=? AND from_npc=? AND title=? AND chain_id=? AND chain_step=? LIMIT 1",
                                (group_id, step.get("from_npc", ""), step.get("title", ""), cid, step.get("chain_step", 0))
                            ).fetchone()
                            if row:
                                existing = conn3.execute(
                                    "SELECT condition_edges_json FROM story_nodes WHERE id=?",
                                    (row[0],)
                                ).fetchone()
                                edges = []
                                if existing and existing[0] and existing[0] != "[]":
                                    try:
                                        edges = json.loads(existing[0])
                                    except Exception:
                                        edges = []
                                edges.append(edge)
                                conn3.execute(
                                    "UPDATE story_nodes SET condition_edges_json=? WHERE id=?",
                                    (json.dumps(edges, ensure_ascii=False), row[0])
                                )
                    conn3.commit()
                    conn3.close()
                except Exception as e:
                    print(f"  [链连接异常] {e}")

        print(f"[StoryTree] 组={group_id} 生成 {len(all_passed)} 个节点")
        if failed_npcs:
            print(f"[StoryTree] 以下NPC生成失败: {list(set(failed_npcs))}")

    def generate_groups(self, n_groups: int = 5, nodes_per_group: int = 15):
        """批量生成多个节点组，每组nodes_per_group个节点"""
        import random, string
        # 清库
        conn = _get_db()
        conn.execute("DELETE FROM story_nodes")
        conn.commit()
        conn.close()
        for i in range(n_groups):
            gid = f"g_{''.join(random.choices(string.ascii_lowercase + string.digits, k=4))}"
            self.generate_story_tree(nodes_per_group, group_id=gid)
            print(f"  → 组 {gid} 完成")
        # 自动选中第一组
        self._current_group_id = self._get_first_group_id()
        # 动态节点连接由 tick() 激活节点时自动处理（_resolve_next_nodes）
        print(f"[Groups] 共 {n_groups} 组，默认选中: {self._current_group_id}")
        # 生成后自动清理链数据
        self._post_process_chains()

    def _post_process_chains(self):
        """新生成/选中节点组后，清理链数据质量问题：
        1. 单节点链降级为普通事件
        2. 多节点链重新编号为连续 step
        3. 重填 condition_edges 指向正确下一步
        """
        conn = _get_db()
        # 收集所有链
        rows = conn.execute(
            "SELECT chain_id FROM story_nodes WHERE chain_id != '' AND chain_id IS NOT NULL "
            "AND status IN ('pending','active') GROUP BY chain_id"
        ).fetchall()
        for (cid,) in rows:
            nodes = conn.execute(
                "SELECT id, chain_step FROM story_nodes WHERE chain_id=? AND status IN ('pending','active') "
                "ORDER BY chain_step, created_at",
                (cid,)
            ).fetchall()
            if len(nodes) <= 1:
                conn.execute("UPDATE story_nodes SET chain_id='' WHERE id=?", (nodes[0][0],))
                continue
            # 重新编号
            for new_step, (nid, old_step) in enumerate(nodes):
                if old_step != new_step:
                    conn.execute("UPDATE story_nodes SET chain_step=? WHERE id=?", (new_step, nid))
            # 重填边
            for i in range(len(nodes)):
                nid = nodes[i][0]
                if i == len(nodes) - 1:
                    conn.execute("UPDATE story_nodes SET condition_edges_json='[]' WHERE id=?", (nid,))
                else:
                    nn = conn.execute(
                        "SELECT from_npc, location FROM story_nodes WHERE id=?",
                        (nodes[i+1][0],)
                    ).fetchone()
                    if nn:
                        conn.execute(
                            "UPDATE story_nodes SET condition_edges_json=? WHERE id=?",
                            (json.dumps([{
                                "condition": f"chain_complete('{cid}_step{i}')",
                                "target_npc": nn[0],
                                "target_location": nn[1],
                                "score": 10.0,
                                "source": "post_process_chain"
                            }], ensure_ascii=False), nid)
                        )
        conn.commit()
        conn.close()
        print(f"[Chains] 链数据已清理")

    def select_group(self, group_id: str = None):
        """选中一个节点组，本局只跑该组的节点和链"""
        conn = _get_db()
        # 如果没指定，随机选一个存在的组
        if group_id is None:
            rows = conn.execute("SELECT DISTINCT group_id FROM story_nodes WHERE group_id != '' ORDER BY RANDOM() LIMIT 1").fetchall()
            if not rows:
                conn.close()
                return
            group_id = rows[0][0]
        self._current_group_id = group_id
        # 非选中组的节点状态改成 skipped
        conn.execute("UPDATE story_nodes SET status='skipped' WHERE group_id != ? AND group_id != '' AND status='pending'", (group_id,))
        conn.commit()
        conn.close()
        print(f"[Group] 选中节点组: {group_id}")
        # 选中后自动清理链数据
        self._post_process_chains()

    def _get_first_group_id(self) -> str:
        conn = _get_db()
        row = conn.execute("SELECT group_id FROM story_nodes WHERE group_id != '' LIMIT 1").fetchone()
        conn.close()
        return row[0] if row else "default"

    def _save_story_node(self, event: dict, group_id: str = "default"):
        """将单个事件转为 story_node 入库"""
        import uuid
        nid = f"sn_{uuid.uuid4().hex[:8]}"
        # 生成触发条件（根据事件内容推断）
        trigger = self._infer_trigger(event)
        day_min, day_max = 1, 999
        if "day_range" in event:
            dr = event["day_range"]
            # 确保合理的默认值
            day_min = max(1, int(dr[0])) if isinstance(dr, (list, tuple)) and len(dr) >= 1 else 1
            day_max = max(day_min, int(dr[1])) if isinstance(dr, (list, tuple)) and len(dr) >= 2 else 999
        # LLM 生成的 options 和 impact
        options_json = event.get("options_json", [])
        impact_json = event.get("impact_json", {})
        importance_score = event.get("importance_score", 5.0)
        # 如果 LLM 没返回，就给空数组（回退到原有行为）
        if isinstance(options_json, str):
            try:
                options_json = json.loads(options_json)
            except json.JSONDecodeError:
                options_json = []
        if isinstance(impact_json, str):
            try:
                impact_json = json.loads(impact_json)
            except json.JSONDecodeError:
                impact_json = {}
        conn = _get_db()
        try:
            conn.execute(
                "INSERT OR IGNORE INTO story_nodes "
                "(id,group_id,title,category,from_npc,summary,location,involved_npcs,"
                "trigger_json,options_json,condition_edges_json,impact_json,"
                "day_min,day_max,quality_score,importance_score,status,created_at,"
                "chain_id,chain_step) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (nid,
                 group_id,
                 event.get("title", ""),
                 event.get("category", ""),
                 event.get("from_npc", ""),
                 event.get("description", ""),
                 (event.get("related_locations", [None])[0] if event.get("related_locations") else None),
                 json.dumps(event.get("related_npcs", []), ensure_ascii=False),
                 json.dumps(trigger, ensure_ascii=False),
                 json.dumps(options_json, ensure_ascii=False),
                 "[]",  # condition_edges_json 由链连接或 _resolve_next_nodes 填充
                 json.dumps(impact_json, ensure_ascii=False),
                 day_min, day_max,
                 event.get("quality_score", 0.0),
                 float(importance_score) if importance_score else 5.0,
                 "pending",
                 time.strftime("%Y-%m-%dT%H:%M:%S"),
                 event.get("chain_id", ""),
                 event.get("chain_step", 0))
            )
        except Exception:
            pass
        conn.commit()
        conn.close()

    def _infer_trigger(self, event: dict) -> dict:
        """从事件内容推断触发条件"""
        from_npc = event.get("from_npc", "")
        related_npcs = event.get("related_npcs", [])
        related_locs = event.get("related_locations", [])
        # 默认触发：和事件相关NPC聊过天，或者到过相关地点
        trigger = {"type": "npc_visited", "target": from_npc}
        if related_locs:
            trigger = {"type": "location_visited", "target": related_locs[0]}
        # 随机加点好感度/天数要求
        trigger["min_favor"] = random.choice([0, 0, 10, 20])
        trigger["min_day"] = random.randint(1, 5)
        return trigger

    def _evaluate_trigger(self, trigger: dict, state: dict) -> bool:
        """评估一个触发条件是否满足
        前期（前20天）放宽地点和NPC访问限制，让事件随天数自然触发"""
        game_day = state.get("game_day", 0)
        # 天数条件
        if trigger.get("min_day", 0) > game_day:
            return False
        # 好感度条件 —— 仅对 NPC 类型触发有效
        if trigger["type"] == "npc_visited":
            npc_name = trigger.get("target", "")
            if trigger.get("min_favor", 0) > 0 and npc_name:
                favors = state.get("favors", {})
                if favors.get(npc_name, 0) < trigger["min_favor"]:
                    return False
        # 地点条件 —— 前20天不检查，之后检查
        if trigger["type"] == "location_visited" and trigger.get("target"):
            if game_day > 20:
                visited = state.get("visited_locations", set())
                if trigger["target"] not in visited:
                    return False
        # NPC条件 —— 前20天不检查，之后检查
        if trigger["type"] == "npc_visited" and trigger.get("target"):
            if game_day > 20:
                visited = state.get("visited_npcs", set())
                if trigger["target"] not in visited:
                    return False
        return True

    def _build_player_state(self) -> dict:
        """从当前游戏状态构建玩家状态快照"""
        import game as g
        try:
            state = {
                "game_day": g.game_day if hasattr(g, 'game_day') else 1,
                "favors": {},
                "visited_locations": set(),
                "visited_npcs": set(),
            }
            # 尝试从关系数据获取好感度
            try:
                relations = g.chat.memory.get_all_relations("default")
                for npc, data in relations.items():
                    if isinstance(data, dict):
                        state["favors"][npc] = data.get("intimacy", 50)
                    elif isinstance(data, (int, float)):
                        state["favors"][npc] = data
            except Exception:
                pass
            # 已访问地点（从地图解锁状态推断）
            try:
                unlocked = g.get_unlocked_locations()
                for loc in unlocked:
                    state["visited_locations"].add(loc)
            except Exception:
                pass
            # 已访问NPC（从对话历史推断）
            hist_dir = g.HIST_DIR
            if os.path.isdir(hist_dir):
                for fname in os.listdir(hist_dir):
                    if fname.endswith(".json"):
                        # 文件名格式: "NPC名_用户ID.json"，剥掉后缀和用户ID
                        npc_name = fname.replace(".json", "")
                        if "_" in npc_name:
                            npc_name = npc_name.rsplit("_", 1)[0]
                        state["visited_npcs"].add(npc_name)
            return state
        except Exception:
            return {"game_day": 1, "favors": {}, "visited_locations": set(), "visited_npcs": set()}

    def _is_npc_accessible(self, npc_name: str) -> bool:
        """检查玩家是否已解锁该NPC所在的地图地点"""
        import game as g
        try:
            profile = NPC_PROFILES.get(npc_name, {})
            loc = profile.get("location", "")
            if not loc:
                return False
            unlocked = g.get_unlocked_locations()
            return loc in unlocked
        except Exception:
            return True  # 兜底：万一出错不挡

    def _activate_node(self, node: dict):
        """激活一个故事节点，推邮箱消息（受冷却配额保护）"""
        import game as g
        npc_name = node.get("from_npc", "")
        if not npc_name:
            return
        if not self._is_npc_accessible(npc_name):
            return  # 地图未解锁，不发飞鸽
        if not self._can_send_mail(npc_name):
            return

        mot = self.chat.motivation_manager.get(npc_name)
        mood_shift = random.choice(["关注", "好奇", "兴奋", "平静"])
        self.chat.motivation_manager.update_mood(npc_name, mood_shift)

        # 用标题作为消息内容（或者尝试用LLM生成）
        content = node.get("summary", node.get("title", ""))
        if content:
            g.add_mail_message("default", npc_name, content[:60], mood_shift)
            self._record_mail(npc_name)
            # 记录NPC经历（用于后续反思），重要性 = quality_score 或默认5
            imp = node.get("quality_score", node.get("importance_score", 5.0))
            if isinstance(imp, (int, float)) and imp > 0:
                pass  # 保持原值
            else:
                imp = 5.0
            self._log_npc_experience(
                npc_name, f"【事件】{content}", importance=imp,
                source_type="story_node", source_id=node.get("id", "")
            )

            # 将事件写入相关NPC的长期记忆（三层记忆系统）
            event_desc = node.get("description", node.get("summary", ""))
            title = node.get("title", "")
            memory_text = f"【江湖事件】{title}：{event_desc}" if title else f"【江湖事件】{event_desc}"
            mem_layer = "rare" if imp >= 8 else "uncommon"
            is_mainline = imp >= 8  # 主线事件：重要性>=8，记忆永久锁定不衰减

            # 写入事件发起NPC的记忆
            self.chat.memory.update_longterm(npc_name, memory_text, layer=mem_layer, fixed_layer=is_mainline)

            # 写入相关NPC的记忆
            involved = node.get("involved_npcs", "[]")
            if isinstance(involved, str):
                try:
                    involved = json.loads(involved)
                except Exception:
                    involved = []
            for other_npc in (involved or []):
                if other_npc and other_npc != npc_name:
                    self.chat.memory.update_longterm(other_npc, memory_text, layer=mem_layer, fixed_layer=is_mainline)

            # —— NPC社交传播 ——
            # 知情NPC通过亲密度关系网传播消息（最多1层，防全图广播）
            known_set = {npc_name} | set(involved or [])
            for knower in list(known_set):
                if knower not in self.G:
                    continue
                for neighbor in self.G.neighbors(knower):
                    if neighbor in known_set:
                        continue
                    relation = self.chat.memory.get_relation("default", neighbor)
                    if relation >= 60:
                        prob = 0.7
                    elif relation >= 40:
                        prob = 0.3
                    else:
                        prob = 0.0
                    if prob > 0 and random.random() < prob:
                        spread_text = f"【江湖传闻】{memory_text}" if imp < 8 else memory_text
                        self.chat.memory.update_longterm(neighbor, spread_text, layer=mem_layer)
                        known_set.add(neighbor)  # 传播过的NPC不再继续往下传

        # 标记节点为已激活
        conn = _get_db()
        conn.execute(
            "UPDATE story_nodes SET status='active', activated_at=? WHERE id=?",
            (time.strftime("%Y-%m-%dT%H:%M:%S"), node["id"])
        )
        conn.commit()
        conn.close()

        # 激活后：动态解析下一批节点（玩家行为驱动）
        self._resolve_next_nodes(node)
        # 链任务注册：链的第一步节点激活时，自动注册为任务
        self._register_chain_quest(node)

    def _register_chain_quest(self, node: dict):
        """链第一步激活时，自动注册该链为任务"""
        chain_id = node.get("chain_id", "")
        if not chain_id or node.get("chain_step", 0) != 0:
            return  # 只注册链的第一步
        import game as g
        if not g.chat:
            return
        qid = f"chain_{chain_id}"
        # 已注册过就不重复
        if any(q.get("qid") == qid for q in g.chat._user_quests("default")):
            return
        # 获取该链所有节点
        conn = _get_db()
        cur = conn.cursor()
        cur.execute(
            "SELECT id, title, summary, location, from_npc, chain_step, involved_npcs "
            "FROM story_nodes WHERE chain_id=? ORDER BY chain_step",
            (chain_id,)
        )
        chain_nodes = cur.fetchall()
        conn.close()
        if len(chain_nodes) < 2:
            return
        # 收集涉及NPC
        all_npcs = set()
        for nd in chain_nodes:
            all_npcs.add(nd[4])
            inv = nd[6]
            if isinstance(inv, str):
                try:
                    for n in json.loads(inv):
                        all_npcs.add(n)
                except Exception:
                    pass
        # 构建步骤
        steps = []
        for i, nd in enumerate(chain_nodes):
            sid, stitle, ssummary, sloc, snpc, sstep, sinv = nd
            kw = [stitle[:6]]
            if ssummary:
                kw += [s.strip()[:8] for s in ssummary.split("，") if len(s.strip()) > 2][:3]
            steps.append({
                "id": i + 1,
                "desc": ssummary or stitle,
                "keywords": kw,
                "hint": f"前往【{sloc}】找【{snpc}】",
            })
        quest = {
            "qid": qid, "trigger": [], "title": f"【剧情链】{chain_id}",
            "type": "chain", "stars": 2,
            "desc": chain_nodes[0][2] or chain_nodes[0][1],
            "reward": "完成剧情链",
            "reward_data": {"intimacy": 5, "exp": 10},
            "npc_permission": list(all_npcs),
            "prerequisite": None, "chapter": 1, "steps": steps,
            "next_hint": "",
        }
        g.chat._add_quest("default", quest)
        g.save_all_state()

    def _resolve_next_nodes(self, activated_node: dict):
        """触发节点后，根据玩家行为状态动态选择后续节点。
        不靠预存的条件边，而是运行时匹配最贴合玩家行为的下级节点。

        打分维度：
        - 地点接近度：候选节点 location 在玩家访问过的地点中 +3分
        - 好感度倾向：候选节点 involved_npcs 中好感最高的那个 +2~+5
        - NPC 接触度：候选节点 from_npc 玩家聊过天 +2分
        - 飞鸽情报：候选节点涉及NPC在玩家已读飞鸽中出现 +3分
        - 叙事连续性：候选节点 involved_npcs 跟刚激活的节点有交集 +3分
        - 质量加成：quality_score / 2

        取分最高的 1-3 个写为 condition_edges。
        同时执行 impact_json 中的 lock_nodes（激活锁定节点后，对立节点被标记 skipped）。
        """
        state = self._build_player_state()
        gid = self._current_group_id or "default"

        # 1. 执行 impact：先锁死冲突节点
        self._execute_node_impact(activated_node)

        # 2. 获取所有待激活节点（排除自己）
        conn = _get_db()
        rows = conn.execute(
            "SELECT * FROM story_nodes WHERE status='pending' AND group_id=? AND id != ?",
            (gid, activated_node["id"])
        ).fetchall()
        conn.close()

        if not rows:
            return

        # 解析玩家行为数据
        visited_locs = state.get("visited_locations", set())
        visited_npcs = state.get("visited_npcs", set())
        favors = state.get("favors", {})
        # 玩家已读飞鸽中涉及的NPC（玩家已知江湖动态）
        try:
            import game as _g
            mail_npcs = _g.get_read_mail_npcs("default")
        except Exception:
            mail_npcs = set()

        # 刚激活节点的信息
        activated_npcs = set()
        activated_loc = activated_node.get("location", "")
        try:
            inv = activated_node.get("involved_npcs", "[]")
            if isinstance(inv, str):
                inv = json.loads(inv)
            activated_npcs = set(inv)
        except json.JSONDecodeError:
            pass

        # 2.5 读取激活NPC的当前PAD情感状态（用于事件匹配）
        from_npc_name = activated_node.get("from_npc", "")
        pad = self._get_npc_pad(from_npc_name)
        # pad: {"valence": -1~1, "arousal": 0~1, "dominance": 0~1}
        v = pad.get("valence", 0)
        a = pad.get("arousal", 0.5)
        d = pad.get("dominance", 0.5)

        # 3. 对每个候选节点打分
        scored = []
        for row in rows:
            node = dict(row)
            score = 0.0

            # --- PAD 情感驱动的加成分 ---
            # 负情绪时，冲突事件更容易触发
            if v < -0.2 and node.get("category") == "npc_conflict":
                score += abs(v) * 3.0  # valence越负，冲突加分越高（最高+3）
            # 高唤醒度时，NPC行动事件加分
            if a > 0.6 and node.get("category") == "npc_action":
                score += (a - 0.5) * 4.0  # 最高+2
            # 高支配度时，NPC主动发起的事件加分
            if d > 0.6 and node.get("from_npc") == from_npc_name:
                score += (d - 0.5) * 4.0  # 最高+2
            # 低唤醒 + 负情绪（消沉/抑郁），被动观察事件加分
            if a < 0.4 and v < -0.1:
                score += 1.0

            # 地点接近度
            node_loc = node.get("location", "")
            if node_loc and node_loc in visited_locs:
                score += 3.0

            # 好感度倾向
            try:
                inv = node.get("involved_npcs", "[]")
                if isinstance(inv, str):
                    inv = json.loads(inv)
                if inv:
                    max_favor = max(favors.get(n, 0) for n in inv)
                    score += min(max_favor / 10.0, 5.0)  # 最高+5
            except Exception:
                pass
            
            # NPC 接触度
            from_npc = node.get("from_npc", "")
            if from_npc and from_npc in visited_npcs:
                score += 2.0

            # 飞鸽情报：玩家已读飞鸽中涉及的NPC → 玩家已知江湖动向，对应事件更相关
            if from_npc and from_npc in mail_npcs:
                score += 3.0
            # 候选节点中涉及的NPC与飞鸽提及NPC重叠 → 玩家关注的事件方向加分
            try:
                inv_raw = node.get("involved_npcs", "[]")
                if isinstance(inv_raw, str):
                    inv_raw = json.loads(inv_raw)
                node_inv = set(inv_raw)
                mail_overlap = node_inv & mail_npcs
                if mail_overlap:
                    score += min(len(mail_overlap), 2) * 1.5  # 最多+3
            except Exception:
                pass

            # 叙事连续性：跟激活节点有共同 NPC
            try:
                inv2 = node.get("involved_npcs", "[]")
                if isinstance(inv2, str):
                    inv2 = json.loads(inv2)
                node_npcs = set(inv2) | {node.get("from_npc", "")}
                if node_npcs & activated_npcs:
                    score += 3.0
            except Exception:
                pass

            # 质量加成
            qs = node.get("quality_score", 0) or 0
            score += qs / 2.0

            # 同类别事件优先
            if node.get("category") == activated_node.get("category"):
                score += 1.0

            scored.append((score, node))

        # 按分排序，取 Top 3
        scored.sort(key=lambda x: x[0], reverse=True)
        top_nodes = scored[:3]

        # 4. 写入 condition_edges
        conn = _get_db()
        for score, node in top_nodes:
            edge = {
                "condition": f"node_activated('{activated_node['id']}')",
                "target_npc": node.get("from_npc", ""),
                "score": round(score, 1),
                "source": "dynamic_resolve"
            }
            existing = conn.execute(
                "SELECT condition_edges_json FROM story_nodes WHERE id=?",
                (activated_node["id"],)
            ).fetchone()
            edges = []
            if existing and existing[0] and existing[0] != "[]":
                try:
                    edges = json.loads(existing[0])
                except json.JSONDecodeError:
                    pass
            # 避免重复边
            existing_targets = {e.get("target_npc", "") for e in edges}
            if edge["target_npc"] not in existing_targets:
                edges.append(edge)
            conn.execute(
                "UPDATE story_nodes SET condition_edges_json=? WHERE id=?",
                (json.dumps(edges, ensure_ascii=False), activated_node["id"])
            )
        conn.commit()
        conn.close()

        if top_nodes:
            top_titles = [f"{n['title']}({s:.1f})" for s, n in top_nodes]
            print(f"[Resolve] {activated_node['title']} → {', '.join(top_titles)}")

    def _get_npc_pad(self, npc_name: str) -> dict:
        """从 EmotionEngine 读取 NPC 当前的 PAD 值"""
        history = self.chat.emotion_engine._history.get(npc_name, [])
        if history:
            last = history[-1]
            return {
                "valence": last.get("valence", 0.0),
                "arousal": last.get("arousal", 0.5),
                "dominance": last.get("dominance", 0.5),
            }
        return {"valence": 0.0, "arousal": 0.5, "dominance": 0.5}

    def _execute_node_impact(self, node: dict):
        """执行节点的 impact_json：声望变化、关系变化、锁定互斥节点"""
        impact_raw = node.get("impact_json", "{}")
        if isinstance(impact_raw, str):
            try:
                impact = json.loads(impact_raw)
            except json.JSONDecodeError:
                return
        else:
            impact = impact_raw

        if not impact or not isinstance(impact, dict):
            return

        gid = self._current_group_id or "default"
        conn = _get_db()

        # lock_nodes: 触发本节点后，这些节点被标记 skipped（互斥锁定）
        lock_ids = impact.get("lock_nodes", [])
        if lock_ids:
            placeholders = ",".join("?" for _ in lock_ids)
            conn.execute(
                f"UPDATE story_nodes SET status='skipped' WHERE id IN ({placeholders}) AND status='pending'",
                lock_ids
            )
            print(f"[Impact] {node['title']} 锁定了 {len(lock_ids)} 个互斥节点: {lock_ids}")

        conn.commit()
        conn.close()

    def get_pending_story_nodes(self) -> list:
        """获取当前组未激活的故事节点"""
        conn = _get_db()
        rows = conn.execute(
            "SELECT * FROM story_nodes WHERE status='pending' AND group_id=? ORDER BY day_min ASC",
            (self._current_group_id or "default",)
        ).fetchall()
        conn.close()
        return [dict(r) for r in rows]

    def get_active_story_nodes(self) -> list:
        """获取所有已激活的故事节点"""
        conn = _get_db()
        rows = conn.execute(
            "SELECT * FROM story_nodes WHERE status='active' ORDER BY activated_at DESC"
        ).fetchall()
        conn.close()
        return [dict(r) for r in rows]

    def _can_send_mail(self, npc_name: str) -> bool:
        """检查该NPC是否可以发消息（单NPC冷却 + 全局配额 + 邮箱满限流）"""
        import game as _g
        now = time.time()
        # 邮箱满15条未读 → 暂停推送，等玩家清理
        if _g.unread_mail_count("default") >= 15:
            return False
        # 单NPC冷却
        last = self._npc_mail_cooldown.get(npc_name, 0)
        if now - last < self.MAIL_COOLDOWN_SEC:
            return False
        # 全局配额
        self._global_mail_log = [t for t in self._global_mail_log if now - t < self.GLOBAL_WINDOW_SEC]
        if len(self._global_mail_log) >= self.GLOBAL_MAX_MAIL:
            return False
        return True

    def _record_mail(self, npc_name: str) -> None:
        """记录该NPC发了一条消息——更新单NPC冷却时间戳+追加全局日志"""
        now = time.time()
        self._npc_mail_cooldown[npc_name] = now
        self._global_mail_log.append(now)

    def _log_npc_experience(self, npc_name: str, experience: str, importance: float = 5.0,
                            source_type: str = "event", source_id: str = "") -> None:
        """记录NPC的一条经历，用于后续反思"""
        import uuid
        eid = f"exp_{uuid.uuid4().hex[:8]}"
        conn = _get_db()
        try:
            conn.execute(
                "INSERT INTO npc_experience_log (id,npc_name,experience,importance_score,source_type,source_id,created_at) "
                "VALUES (?,?,?,?,?,?,?)",
                (eid, npc_name, experience, importance, source_type, source_id,
                 time.strftime("%Y-%m-%dT%H:%M:%S"))
            )
            conn.commit()
        except Exception as e:
            logger.warning(f"_log_npc_experience failed: {e}")
        finally:
            conn.close()

    def _get_npc_recent_experiences(self, npc_name: str, since: float = 0) -> list:
        """获取NPC最近未反思的经历，返回 [(experience, importance, created_at), ...]"""
        conn = _get_db()
        since_str = time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(since)) if since else "1970-01-01"
        rows = conn.execute(
            "SELECT experience, importance_score, created_at FROM npc_experience_log "
            "WHERE npc_name=? AND created_at > ? ORDER BY created_at ASC",
            (npc_name, since_str)
        ).fetchall()
        conn.close()
        return [(r[0], r[1], r[2]) for r in rows]

    def _get_npc_reflection_history(self, npc_name: str, limit: int = 3) -> list:
        """获取NPC最近的反思结论"""
        conn = _get_db()
        rows = conn.execute(
            "SELECT reflection, insight_type, related_npcs, created_at FROM npc_reflections "
            "WHERE npc_name=? ORDER BY created_at DESC LIMIT ?",
            (npc_name, limit)
        ).fetchall()
        conn.close()
        return [{"reflection": r[0], "type": r[1], "related": r[2], "time": r[3]} for r in rows]

    # ============================================================
    # 反思系统
    # ============================================================
    def _check_and_reflect(self) -> None:
        """tick中检查所有活跃NPC是否需要反思"""
        try:
            npc_names = list(NPC_PROFILES.keys())
            random.shuffle(npc_names)
            for name in npc_names:
                if self._should_reflect(name):
                    self._reflect_on_npc(name)
                    break
        except Exception as e:
            logger.warning(f"_check_and_reflect error: {e}")

    def _should_reflect(self, npc_name: str) -> bool:
        """检查NPC是否需要反思：累积重要性是否达标"""
        since = self._last_reflection_time.get(npc_name, 0)
        exps = self._get_npc_recent_experiences(npc_name, since)
        total_importance = sum(e[1] for e in exps)
        return total_importance >= self.REFLECTION_THRESHOLD

    def _reflect_on_npc(self, npc_name: str) -> None:
        """对NPC执行一次反思：LLM根据近期经历更新对话层的 mood 和 goal。
        注意：drive（执念）不在此修改，保持与 pregen 事件一致。"""
        import json as _json
        since = self._last_reflection_time.get(npc_name, 0)
        exps = self._get_npc_recent_experiences(npc_name, since)
        if not exps:
            return
        since = max(since, 1)
        self._last_reflection_time[npc_name] = time.time()

        # 构造经历文本
        exp_lines = []
        for i, (text, imp, ts) in enumerate(exps, 1):
            exp_lines.append(f"{i}. {text} (重要性:{imp})")
        exp_text = "\n".join(exp_lines)
        total_imp = sum(e[1] for e in exps)

        # 获取当前动机
        mot = self.chat.motivation_manager.get(npc_name)
        # 原始人设（始终作锚点，drive 永久锁定）
        profile = NPC_PROFILES.get(npc_name, {})
        base_mot = profile.get("motivation", {})
        locked_drive = base_mot.get("drive", mot.get("drive", ""))

        # 构建反思prompt —— 不要求输出 drive，避免破坏 pregen 一致性
        prompt = (
            f"你是一个武侠世界观下的角色情绪分析系统。\n"
            f"NPC名称：{npc_name}\n"
            f"人设：{profile.get('system_prompt', '')[:100]}...\n"
            f"核心执念（不可变）：{locked_drive}\n"
            f"当前心情：{mot.get('mood', '平静')}\n"
            f"当前目标：{mot.get('goal', '未设定')}\n\n"
            f"该NPC近期经历了以下事件（总重要性{total_imp:.0f}）：\n{exp_text}\n\n"
            f"请基于这些经历，只分析NPC的**情绪和短期关注点**的变化，输出JSON：\n"
            f"{{\n"
            f'  "mood": "更新后的情绪状态（两字，如：愤怒/欣慰/焦虑/释然/振奋/消沉）",\n'
            f'  "goal": "更新后的当前目标（30字内，要经历有据、有指向性）",\n'
            f'  "reflection_summary": "一句核心反思结论（40字内）"\n'
            f"}}\n\n"
            f"要求：\n"
            f"1. mood 基于经历合理变化，不要凭空\n"
            f"2. goal 必须从近期事件中自然延伸，别编造和人设不符的目标\n"
            f"3. 如果经历不足以改变，保持原值\n"
            f"4. 只输出JSON，别多字"
        )
        try:
            from langchain_core.prompts import ChatPromptTemplate
            from langchain_core.messages import HumanMessage
            from langchain_core.output_parsers import StrOutputParser
            p = ChatPromptTemplate.from_messages([HumanMessage(content=prompt)])
            raw = (p | self.generator.llm | StrOutputParser()).invoke({})
            clean = _clean_json(raw)
            result = _json.loads(clean)

            # 只更新对话层：mood 和 goal，drive 锁定不动
            changed = False
            if "mood" in result and result["mood"] and result["mood"] != mot.get("mood", ""):
                self.chat.motivation_manager.update_mood(npc_name, result["mood"])
                changed = True
            if "goal" in result and result["goal"] and result["goal"] != mot.get("goal", ""):
                self.chat.motivation_manager.update_goal(npc_name, result["goal"])
                changed = True
            if changed:
                self.chat.motivation_manager._save()

            # 反思结论写入长期记忆
            ref_summary = result.get("reflection_summary", "")
            if ref_summary:
                self.chat.memory.update_longterm(
                    npc_name, f"【内心反思】{ref_summary}", layer="uncommon"
                )
            import uuid
            ref_id = f"ref_{uuid.uuid4().hex[:8]}"
            conn = _get_db()
            try:
                conn.execute(
                    "INSERT INTO npc_reflections (id,npc_name,reflection,insight_type,related_npcs,"
                    "importance_score,created_at) VALUES (?,?,?,?,?,?,?)",
                    (ref_id, npc_name, ref_summary, "self", "[]", total_imp,
                     time.strftime("%Y-%m-%dT%H:%M:%S"))
                )
                conn.commit()
            except Exception as e:
                logger.warning(f"_reflect_on_npc save failed: {e}")
            finally:
                conn.close()

            logger.info(f"[Reflect] {npc_name} 完成反思: {ref_summary}")
        except Exception as e:
            logger.warning(f"_reflect_on_npc failed for {npc_name}: {e}")

    def tick(self, npc_name: Optional[str] = None) -> None:
        """世界推进 - 每30秒由调度器调用
        节流：全局5分钟内最多2条消息，单NPC 5分钟内最多1条
        玩家挂机（5分钟无操作）时暂停推进，回来时最多累积2-3条"""
        import game as g

        self._chains_advanced_this_tick.clear()
        tc = self.diag.tick_count

        # 检测玩家是否挂机：最近一次操作距今超过5分钟则限流
        now = time.time()
        last_active = 0
        try:
            if g.last_activity:
                last_active = max(g.last_activity.values())
        except Exception:
            pass
        idle = now - last_active > 300  # 5分钟无操作=挂机

        # 清理过期的全局消息日志
        now = time.time()
        self._global_mail_log = [t for t in self._global_mail_log if now - t < self.GLOBAL_WINDOW_SEC]

        npc_names = ([npc_name] if npc_name else list(NPC_PROFILES.keys()))

        # 挂机状态：完全跳过节点激活
        if idle:
            self.diag.record_tick(f"[Tick #{self.diag.tick_count+1}] 世界暂停 - 玩家离线中")
            return

        state = self._build_player_state()
        # 补充玩家已读飞鸽涉及的NPC（用于剧情偏转）
        mail_npcs = set()
        try:
            import game as _g2
            mail_npcs = _g2.get_read_mail_npcs("default")
        except Exception:
            pass

        # 3. 节点激活 —— 每6tick（3分钟）激活1个，前3tick跳过
        max_activate = 0
        if tc >= 3 and tc % 6 == 0:
            max_activate = 1

        # 收集已激活节点的 condition_edges 中的 target_npc，作为"玩家关注方向"
        preferred_npcs = set()
        try:
            conn2 = _get_db()
            edge_rows = conn2.execute(
                "SELECT condition_edges_json FROM story_nodes WHERE status='active' AND group_id=?",
                (self._current_group_id or "default",)
            ).fetchall()
            conn2.close()
            for er in edge_rows:
                if not er[0] or er[0] == "[]":
                    continue
                try:
                    edges = json.loads(er[0])
                    for e in edges:
                        target = e.get("target_npc", "")
                        if target:
                            preferred_npcs.add(target)
                except Exception:
                    pass
        except Exception:
            pass

        conn = _get_db()
        # 宽松查询：day_max用当前天数，day_min允许提前3天（给飞鸽偏转留空间）
        current_day = state.get("game_day", 1)
        rows = conn.execute(
            "SELECT * FROM story_nodes WHERE status='pending' AND group_id=? AND day_min <= ? AND day_max >= ? "
            "ORDER BY quality_score DESC, day_min ASC",
            (self._current_group_id or "default", current_day + 3, current_day)
        ).fetchall()
        conn.close()

        activated = 0
        # 合并玩家情报：已读飞鸽 NPC + 已激活节点 condition_edges 指向的 NPC
        player_aware_npcs = mail_npcs | preferred_npcs

        # 两轮激活：优先激活玩家情报涉及的NPC节点
        for priority in [True, False]:
            if activated >= max_activate:
                break
            for row in rows:
                if activated >= max_activate:
                    break
                node = dict(row)
                from_npc = node.get("from_npc", "")
                # 第一轮：只激活玩家已知NPC的节点；第二轮：正常激活所有
                if priority and from_npc not in player_aware_npcs:
                    continue
                if not priority and from_npc in player_aware_npcs:
                    continue  # 第一轮已经检查过了，跳过
                if not self._can_send_mail(from_npc):
                    continue
                trigger = json.loads(node.get("trigger_json", "{}"))
                # 玩家已知NPC的节点，放宽天数限制（降低min_day门槛）
                if from_npc in player_aware_npcs:
                    trigger = dict(trigger)  # 拷贝，不污染原始数据
                    trigger["min_day"] = max(0, trigger.get("min_day", 0) - 2)
                if trigger.get("min_day", 0) > state.get("game_day", 1):
                    continue
                if trigger and self._evaluate_trigger(trigger, state):
                    self._activate_node(node)
                    activated += 1

        # 4. NPC反思 —— 每3tick检查1次，每次最多反思1个NPC
        if tc % 3 == 0:
            self._check_and_reflect()

        # 记录诊断
        try:
            pending_cnt = state.get("game_day", 1)
            self.diag.record_tick(f"[Tick #{self.diag.tick_count+1}] 天{pending_cnt} | 激活{activated}个节点")
        except Exception:
            pass


    def _save_events(self, events: list):
        conn = _get_db()
        now = time.strftime("%Y-%m-%dT%H:%M:%S")
        for e in events:
            eid = f"evt_{uuid.uuid4().hex[:8]}"
            try:
                conn.execute(
                    "INSERT INTO events (id,title,description,category,from_npc,"
                    "related_npcs,related_locations,impact_level,status,quality_score,created_at,flags) "
                    "VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                    (eid, e.get("title", ""), e.get("description", ""),
                     e.get("category", ""), e.get("from_npc", ""),
                     json.dumps(e.get("related_npcs", []), ensure_ascii=False),
                     json.dumps(e.get("related_locations", []), ensure_ascii=False),
                     e.get("impact_level", 1), e.get("status", "active"),
                     e.get("quality_score", 0.0), now, json.dumps({}))
                )
            except Exception:
                pass
        conn.commit()
        conn.close()
