# -*- coding: utf-8 -*-
"""
core.py — 江湖百晓生 v2.0 引擎层
EmotionEngine 情感计算 / ActionParser 动作提取 / MemoryManager 记忆持久化
"""
import datetime
import json
import re
import time
import sys
from pathlib import Path

from utils import clamp, now_iso
from prompts import ACTION_LIBRARY, EMOTION_LABELS


# ============================================================
# 跨平台文件锁：Unix 用 fcntl，Windows 用 msvcrt
# ============================================================
if sys.platform == "win32":
    import msvcrt

    def _read_json(path: Path) -> dict:
        """带锁读取 JSON（Windows msvcrt），失败重试一次"""
        for _ in range(2):
            try:
                with open(path, "r", encoding="utf-8") as f:
                    msvcrt.locking(f.fileno(), msvcrt.LK_LOCK, 0)
                    try:
                        return json.load(f)
                    finally:
                        try:
                            msvcrt.locking(f.fileno(), msvcrt.LK_UNLCK, 0)
                        except Exception:
                            pass
            except (IOError, OSError):
                time.sleep(0.05)
        return {}

    def _write_json(path: Path, data: dict) -> bool:
        """带锁写入 JSON（Windows msvcrt），失败重试一次"""
        for _ in range(2):
            try:
                path.parent.mkdir(parents=True, exist_ok=True)
                with open(path, "w", encoding="utf-8") as f:
                    msvcrt.locking(f.fileno(), msvcrt.LK_LOCK, 0)
                    try:
                        json.dump(data, f, ensure_ascii=False)
                    finally:
                        try:
                            msvcrt.locking(f.fileno(), msvcrt.LK_UNLCK, 0)
                        except Exception:
                            pass
                return True
            except (IOError, OSError):
                time.sleep(0.05)
        return False

else:
    import fcntl

    def _read_json(path: Path) -> dict:
        """带共享锁读取 JSON（Unix），失败重试一次"""
        for _ in range(2):
            try:
                with open(path, "r", encoding="utf-8") as f:
                    fcntl.flock(f.fileno(), fcntl.LOCK_SH)
                    try:
                        return json.load(f)
                    finally:
                        fcntl.flock(f.fileno(), fcntl.LOCK_UN)
            except (IOError, OSError):
                time.sleep(0.05)
        return {}

    def _write_json(path: Path, data: dict) -> bool:
        """带排他锁写入 JSON（Unix），失败重试一次"""
        for _ in range(2):
            try:
                path.parent.mkdir(parents=True, exist_ok=True)
                with open(path, "w", encoding="utf-8") as f:
                    fcntl.flock(f.fileno(), fcntl.LOCK_EX)
                    try:
                        json.dump(data, f, ensure_ascii=False)
                    finally:
                        fcntl.flock(f.fileno(), fcntl.LOCK_UN)
                return True
            except (IOError, OSError):
                time.sleep(0.05)
        return False


# ============================================================
# EmotionEngine
# ============================================================
class EmotionEngine:
    EMOTION_JSON_RE = re.compile(
        r'\{[^{}]*"emotion"\s*:\s*\{[^}]+\}[^{}]*\}',
        re.DOTALL
    )

    def __init__(self):
        self._history: dict[str, list[dict]] = {}

    def infer(self, llm_raw: str, npc_name: str) -> dict:
        match = self.EMOTION_JSON_RE.search(llm_raw)
        if not match:
            return self._default()
        try:
            data = json.loads(match.group())
            raw = data.get("emotion", {})
        except json.JSONDecodeError:
            return self._default()

        primary = raw.get("primary", "neutral")
        if primary not in EMOTION_LABELS:
            primary = "neutral"

        emotion = {
            "primary":      primary,
            "secondary":   raw.get("secondary"),
            "intensity":    clamp(float(raw.get("intensity", 0.5)), 0.0, 1.0),
            "valence":      clamp(float(raw.get("valence",   0.0)), -1.0, 1.0),
            "arousal":      clamp(float(raw.get("arousal",   0.5)),  0.0, 1.0),
            "dominance":    clamp(float(raw.get("dominance", 0.5)),  0.0, 1.0),
            "trend":        raw.get("trend", "stable"),
            "trigger_word": raw.get("trigger_word", ""),
        }

        history = self._history.setdefault(npc_name, [])
        if history:
            last = history[-1]
            if emotion["primary"] == last["primary"]:
                # 强度几乎相等 → stable，不应强行归为 decreasing
                if abs(emotion["intensity"] - last["intensity"]) < 0.01:
                    emotion["trend"] = "stable"
                else:
                    emotion["trend"] = (
                        "increasing" if emotion["intensity"] > last["intensity"]
                        else "decreasing"
                    )
            # 类型变了保持 LLM 填的 trend（通常是 stable，无需覆盖）

        history.append(emotion)
        return emotion

    def decay(self, npc_name: str, seconds_idle: float) -> dict:
        if seconds_idle < 60:
            return self._history.get(npc_name, [self._default()])[-1]
        # 闲置超60秒：重置为中性，并追加记录保证历史一致
        decay_record = {"primary": "neutral", "secondary": None,
                        "intensity": 0.0, "trend": "decreasing",
                        "valence": 0.0, "arousal": 0.5, "dominance": 0.5,
                        "trigger_word": ""}
        history = self._history.setdefault(npc_name, [])
        history.append(decay_record)
        return decay_record

    def _default(self) -> dict:
        return {"primary": "neutral", "secondary": None,
                "intensity": 0.5, "trend": "stable",
                "valence": 0.0, "arousal": 0.5, "dominance": 0.5,
                "trigger_word": ""}


# ============================================================
# ActionParser
# ============================================================
class ActionParser:
    # 修复：允许 actions:[] 空数组（.*? 而非 [^\]]+，且支持空）
    ACTIONS_JSON_RE = re.compile(
        r'\{[^{}]*"actions"\s*:\s*\[.*?\][^{}]*\}',
        re.DOTALL
    )

    def parse(self, llm_raw: str) -> list:
        match = self.ACTIONS_JSON_RE.search(llm_raw)
        if not match:
            return ["idle"]
        try:
            raw_tags: list = json.loads(match.group()).get("actions", [])
        except json.JSONDecodeError:
            return ["idle"]
        # 只保留在 ACTION_LIBRARY 中的标签（不过滤 idle，由末尾兜底处理）
        filtered = [t for t in raw_tags if t in ACTION_LIBRARY]
        return filtered[:2] if filtered else ["idle"]


# ============================================================
# MemoryParser — 提取 LLM 输出的记忆内容
# ============================================================
class MemoryParser:
    MEMORY_JSON_RE = re.compile(
        r'\{"memory"\s*:\s*"(【记忆】[^"]+)"\}',
        re.DOTALL
    )

    def parse(self, llm_raw: str) -> str | None:
        """提取 memory 文本，无则返回 None"""
        match = self.MEMORY_JSON_RE.search(llm_raw)
        if not match:
            return None
        text = match.group(1)
        # 去掉末尾的句号或特殊字符，保留核心内容
        return text.strip()


# ============================================================
# MemoryManager
# ============================================================
class MemoryManager:
    MAX_SHORT_TERM = 50

    def __init__(self, base_dir: str):
        self.base = Path(base_dir) / "memory"
        self.base.mkdir(parents=True, exist_ok=True)
        (self.base / "longterm").mkdir(exist_ok=True)
        self.relation_file = self.base / "relation.json"
        self.world_file    = self.base / "world_state.json"
        self._init_defaults()

    def _init_defaults(self):
        if not self.relation_file.exists():
            _write_json(self.relation_file, {"default": {}})
        if not self.world_file.exists():
            _write_json(self.world_file, {"completed_quests": [], "world_events": []})

    def save_turn(self, npc_name: str, turn: dict) -> dict:
        sf = self._session_file(npc_name)
        data: dict = _read_json(sf)
        if "turns" not in data:
            data = {"turns": []}
        data["turns"].append(turn)
        if len(data["turns"]) > self.MAX_SHORT_TERM:
            data["turns"] = data["turns"][-self.MAX_SHORT_TERM:]
        _write_json(sf, data)
        delta = turn.get("relation_delta", 0)
        if delta:
            self.update_relation("default", npc_name, delta)
        return {"relation_change": {npc_name: delta}}

    def get_short_term(self, npc_name: str) -> list:
        sf = self._session_file(npc_name)
        return _read_json(sf).get("turns", [])

    def _session_file(self, npc_name: str) -> Path:
        return self.base / f"session_{npc_name}_{datetime.date.today().isoformat()}.json"

    def update_relation(self, user_id: str, npc_name: str, delta: int) -> int:
        rel: dict = _read_json(self.relation_file)
        rel.setdefault(user_id, {}).setdefault(npc_name, {"intimacy": 50, "last_interact": ""})
        rel[user_id][npc_name]["intimacy"] = clamp(
            rel[user_id][npc_name]["intimacy"] + delta, 0, 100)
        rel[user_id][npc_name]["last_interact"] = now_iso()
        _write_json(self.relation_file, rel)
        return rel[user_id][npc_name]["intimacy"]

    def get_relation(self, user_id: str, npc_name: str) -> int:
        rel: dict = _read_json(self.relation_file)
        return rel.get(user_id, {}).get(npc_name, {}).get("intimacy", 50)

    def get_all_relations(self, user_id: str = "default") -> dict:
        rel: dict = _read_json(self.relation_file)
        return rel.get(user_id, {})

    def update_longterm(self, npc_name: str, event: str):
        ltf = self.base / "longterm" / f"{npc_name}_summary.json"
        data: dict = _read_json(ltf)
        if not data:
            data = {"npc_name": npc_name, "summary": "", "key_events": []}
        # 改用集合做去重判断，O(1) 而非 O(n)
        event_set = {e["event"] for e in data["key_events"]}
        if event not in event_set:
            data["key_events"].append({"event": event, "date": now_iso()})
        if len(data["key_events"]) > 100:
            data["key_events"] = data["key_events"][-100:]
        data["last_updated"] = now_iso()
        _write_json(ltf, data)

    def get_longterm(self, npc_name: str) -> dict:
        ltf = self.base / "longterm" / f"{npc_name}_summary.json"
        data = _read_json(ltf)
        return data if data else {"npc_name": npc_name, "summary": "", "key_events": []}

    def complete_quest(self, qid: str, user_id: str = "default"):
        """记录用户完成的任务（per-user）"""
        ws: dict = _read_json(self.world_file)
        if "user_completed_quests" not in ws:
            ws["user_completed_quests"] = {}
        if user_id not in ws["user_completed_quests"]:
            ws["user_completed_quests"][user_id] = []
        if qid not in ws["user_completed_quests"][user_id]:
            ws["user_completed_quests"][user_id].append(qid)
            _write_json(self.world_file, ws)

    def get_completed_quests(self, user_id: str = "default") -> list:
        """获取用户已完成的任务列表"""
        ws: dict = _read_json(self.world_file)
        return ws.get("user_completed_quests", {}).get(user_id, [])

    def add_world_event(self, event: str):
        ws: dict = _read_json(self.world_file)
        if event not in ws.get("world_events", []):
            ws.setdefault("world_events", []).append(event)
            _write_json(self.world_file, ws)
