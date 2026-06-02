# -*- coding: utf-8 -*-
"""
core.py — 江湖百晓生 v2.0 引擎层
EmotionEngine 情感计算 / ActionParser 动作提取 / MemoryManager 记忆持久化 / MotivationManager 动机管理
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

    # 权重分层阈值
    WEIGHT_RARE = 70      # >=70 → 稀缺层
    WEIGHT_UNCOMMON = 30  # >=30 → 不常用层
    # 初始权重映射（low 层不设初始值，靠衰减自然降级）
    INITIAL_WEIGHT = {"uncommon": 40, "rare": 80}
    # 固定分类关键词（rare 命中后 layer 锁定，不参与升降级）
    FIXED_RARE = {"任务完成", "击杀", "击败", "获得秘籍", "学会",
                  "觉醒", "突破", "继承", "传承", "决战", "九阴"}

    def _classify_event(self, event: str) -> tuple:
        """自动分类：返回 (layer, fixed_layer)
        两层结构：rare（最在意的事）和 uncommon（一般经历）
        low 层不由自动分类产生，而是由权重衰减自然降至。
        """
        for kw in self.FIXED_RARE:
            if kw in event:
                return ("rare", True)
        return ("uncommon", False)

    def _compute_effective_weight(self, evt: dict) -> int:
        """计算记忆的有效权重（基础权重 - 时间衰减）"""
        w = evt.get("weight", 40)
        last_ref = evt.get("last_referenced", evt.get("date", ""))
        if last_ref:
            try:
                last_ts = time.mktime(time.strptime(last_ref[:19], "%Y-%m-%dT%H:%M:%S"))
                days_since = max(0, (time.time() - last_ts) / 86400)
                w = max(0, w - int(days_since) * 2)
            except Exception:
                pass
        return w

    def _recalc_layer(self, evt: dict, effective_weight: int) -> str:
        """根据有效权重重新计算层级（固定层不参与）
        两层制：rare / uncommon / low（权重太低不展示）
        """
        if evt.get("fixed_layer", False):
            return evt["layer"]
        if effective_weight >= self.WEIGHT_RARE:
            return "rare"
        elif effective_weight >= self.WEIGHT_UNCOMMON:
            return "uncommon"
        else:
            return "low"

    def update_longterm(self, npc_name: str, event: str, layer: str = None,
                        fixed_layer: bool = None):
        """添加一条长期记忆（自动分类 + 权重 + 升降级）
        layer=None → 自动分类；传值则用该值（但 fixed_layer 仍由关键词决定）
        """
        # 自动分类
        if layer is None:
            layer, fixed_layer = self._classify_event(event)
        elif fixed_layer is None:
            _, fixed_layer = self._classify_event(event)
            # 如果自动分类判定为固定层，保留自动分类的结果
            if fixed_layer:
                layer, _ = self._classify_event(event)
        initial_weight = self.INITIAL_WEIGHT.get(layer, 40)

        ltf = self.base / "longterm" / f"{npc_name}_summary.json"
        data: dict = _read_json(ltf)
        if not data:
            data = {"npc_name": npc_name, "summary": "", "key_events": []}
        events = data["key_events"]

        # 已有相同事件 → 加重权重（不重复添加）
        now = now_iso()
        for e in events:
            if e["event"] == event:
                if not e.get("fixed_layer", False):
                    e["weight"] = min(100, e.get("weight", initial_weight) + 5)
                    e["last_referenced"] = now
                data["last_updated"] = now
                _write_json(ltf, data)
                return

        # 新记忆
        events.append({
            "event": event, "date": now, "layer": layer,
            "weight": initial_weight, "last_referenced": now,
            "fixed_layer": fixed_layer
        })
        # 清理：权重归零的非固定记忆直接删除
        events = [e for e in events
                  if e.get("fixed_layer", False) or self._compute_effective_weight(e) > 0]
        data["key_events"] = events
        data["last_updated"] = now
        _write_json(ltf, data)

    def record_references(self, npc_name: str, referenced_events: list) -> None:
        """被检索到的记忆：权重+3，更新引用时间。同时全局衰减 + 重算层级。"""
        ltf = self.base / "longterm" / f"{npc_name}_summary.json"
        data: dict = _read_json(ltf)
        if not data:
            return
        events = data.get("key_events", [])
        if not events:
            return

        ref_set = set(referenced_events)
        now = now_iso()
        changed = False

        for e in events:
            # 引用加成
            if e["event"] in ref_set and not e.get("fixed_layer", False):
                e["weight"] = min(100, e.get("weight", 40) + 3)
                e["last_referenced"] = now
                changed = True
            # 全局衰减 + 重算层级
            if not e.get("fixed_layer", False):
                eff_w = self._compute_effective_weight(e)
                e["weight"] = eff_w
                e["layer"] = self._recalc_layer(e, eff_w)
                changed = True

        # 清理权重归零的非固定记忆
        events = [e for e in events
                  if e.get("fixed_layer", False) or e.get("weight", 0) > 0]
        data["key_events"] = events

        if changed:
            data["last_updated"] = now
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


# ============================================================
# MotivationManager — NPC 动机状态管理
# ============================================================
class MotivationManager:
    """管理 NPC 的动机/心情/目标状态，支持 JSON 持久化"""

    def __init__(self, base_dir: str, npc_profiles: dict):
        self.base = Path(base_dir) / "state"
        self.base.mkdir(parents=True, exist_ok=True)
        self.motivations_file = self.base / "motivations.json"
        self.npc_profiles = npc_profiles
        self._state: dict[str, dict] = {}
        self._last_message_time: dict[str, float] = {}
        self.MESSAGE_COOLDOWN = 600  # 每10分钟最多发一条消息
        self._load()

    def _load(self):
        """从 JSON 加载，缺失的从 npc_profiles 初始化"""
        saved = _read_json(self.motivations_file)
        for npc_name in self.npc_profiles:
            cfg = self.npc_profiles[npc_name].get("motivation", {})
            if npc_name in saved:
                self._state[npc_name] = saved[npc_name]
            else:
                self._state[npc_name] = {
                    "drive": cfg.get("drive", ""),
                    "mood": cfg.get("mood", "平静"),
                    "goal": cfg.get("goal", ""),
                }
        if not saved:
            self._save()

    def _save(self):
        _write_json(self.motivations_file, self._state)

    def get(self, npc_name: str) -> dict:
        return self._state.get(npc_name, {
            "drive": "", "mood": "平静", "goal": ""
        })

    def update_mood(self, npc_name: str, mood: str):
        """更新 NPC 心情"""
        if npc_name in self._state:
            self._state[npc_name]["mood"] = mood
            self._save()

    def update_goal(self, npc_name: str, goal: str):
        """更新 NPC 目标"""
        if npc_name in self._state:
            self._state[npc_name]["goal"] = goal
            self._save()

    def should_message(self, npc_name: str) -> bool:
        """判断 NPC 是否应该主动发消息（冷却检查，基于话痨系数）"""
        now = time.time()
        last = self._last_message_time.get(npc_name, 0)

        # 从 NPC 配置获取话痨系数，默认 0.5
        profile = self.npc_profiles.get(npc_name, {})
        talk = profile.get("talkativeness", 0.5)
        # cooldown = 300 / max(0.05, talk) → 话痨系数越高，冷却越短
        cooldown = int(300 / max(0.05, talk))

        if now - last < cooldown:
            return False
        self._last_message_time[npc_name] = now
        return True
