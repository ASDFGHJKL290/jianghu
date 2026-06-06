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

    # ── 新记忆系统：四层按性质分类 ────────────────────────────

    # NPC 感官偏好向量 [visual, auditory, logical, emotional]
    # 仅影响经历层记忆权重，不影响当前对话感知
    NPC_SENSES = {
        "店小二":   [0.4, 0.8, 0.3, 0.7],
        "武林盟主": [0.5, 0.6, 0.7, 0.5],
        "神秘大侠": [0.6, 0.3, 0.6, 0.4],
        "扫地僧":   [0.1, 0.6, 0.8, 0.2],
        "洪七公":   [0.5, 0.4, 0.3, 0.6],
        "风清扬":   [0.7, 0.3, 0.8, 0.2],
        "黄衫女":   [0.9, 0.5, 0.6, 0.3],
        "唐巧":     [0.4, 0.3, 0.8, 0.2],
        "任盈盈":   [0.5, 0.9, 0.4, 0.7],
        "任我行":   [0.4, 0.5, 0.6, 0.6],
        "欧阳克":   [0.6, 0.5, 0.7, 0.5],
        "瑛姑":     [0.3, 0.4, 0.5, 0.9],
        "平一指":   [0.5, 0.3, 0.7, 0.2],
    }

    # NPC 专业领域标签 {npc: [关键词列表]}
    NPC_EXPERTISE = {
        "平一指": ["伤", "病", "毒", "脉", "药", "医", "治疗", "看病"],
        "洪七公": ["吃", "肉", "酒", "丐帮", "打狗棒", "叫化鸡"],
        "风清扬": ["剑", "招", "独孤", "武学", "剑法", "招式"],
        "唐巧":   ["毒", "暗器", "机关", "唐门", "淬毒"],
        "黄衫女": ["医", "药", "桃花", "奇门", "五行"],
    }

    # 感官类型关键词
    SENSE_KEYWORDS = {
        "visual":    ["颜色", "穿", "衣服", "场景", "地图", "外观",
                      "红色", "黑色", "白色", "金色", "蓝色", "绿色",
                      "紫色", "灰色", "青", "翠", "碧"],
        "auditory":  ["说", "话", "叫", "喊", "声音", "听", "响", "唱", "曲",
                      "琴", "箫", "音", "歌", "语", "言", "谈", "讲"],
        "logical":   ["因为", "所以", "原因", "结果", "任务", "步骤", "方法",
                      "推理", "机关", "阵法", "规律", "逻辑", "分析",
                      "策略", "计划", "方案"],
        "emotional": ["生气", "高兴", "伤心", "愤怒", "开心", "怕", "爱", "恨",
                      "仇", "恩", "怨", "感动", "委屈", "背叛", "骂", "怒",
                      "哭", "笑", "悲", "喜", "惊", "恐", "羞", "愧"],
    }
    SENSE_VERBS = {
        "visual":    {"看", "见", "望", "瞥", "瞄", "披", "戴", "观", "察"},
        "auditory":  {"说", "问", "答", "喊", "叫", "唤", "唱", "吟", "诵", "呼"},
        "logical":   {"算", "解", "推", "排", "列", "布", "筹", "划", "谋"},
        "emotional": {"哭", "笑", "怒", "恨", "爱", "怜", "惧", "惊", "叹", "泣"},
    }

    # 权重配置默认值
    W_FREQ = 0.25
    W_IMP = 0.20
    W_EMO = 0.15
    W_RECENCY = 0.20
    W_SENSE = 0.10
    W_EXPERTISE = 0.10

    # 衰减参数
    GAMMA_BASE = 0.95
    GAMMA_AGE_SLOPE = 0.04
    CONSOLIDATE_BOOST = 1.02

    # 压力衰减
    PRESSURE_RATE = 3  # 条/分钟
    PRESSURE_MIN = 0.90

    # 固化
    FIXED_THRESHOLD = 5  # access_count ≥ 5 自动固化
    FIXED_EMO_IMP = 0.8  # E*I > 0.8 且 count≥2 固化
    FORGET_DAYS = 30

    def _detect_sense_type(self, event: str) -> str:
        """判定事件的主要感官类型：关键词 + 动词兜底"""
        scores = {"visual": 0, "auditory": 0, "logical": 0, "emotional": 0}
        for sense, kws in self.SENSE_KEYWORDS.items():
            scores[sense] = sum(1 for kw in kws if kw in event)
        best = max(scores, key=scores.get)
        if scores[best] >= 2:
            return best
        verb_scores = {"visual": 0, "auditory": 0, "logical": 0, "emotional": 0}
        for sense, verbs in self.SENSE_VERBS.items():
            verb_scores[sense] = sum(1 for v in verbs if v in event)
        verb_best = max(verb_scores, key=verb_scores.get)
        if verb_scores[verb_best] >= 1:
            return verb_best
        total = {k: scores[k] + verb_scores[k] for k in scores}
        total_best = max(total, key=total.get)
        if total[total_best] > 0:
            return total_best
        return "general"

    def _detect_expertise(self, npc_name: str, event: str) -> bool:
        """判定事件是否命中 NPC 专业领域"""
        kws = self.NPC_EXPERTISE.get(npc_name, [])
        return any(kw in event for kw in kws)

    def _get_sense_match(self, npc_name: str, sense_type: str) -> float:
        """感官匹配分 S"""
        vec = self.NPC_SENSES.get(npc_name, [0.5, 0.5, 0.5, 0.5])
        idx = {"visual": 0, "auditory": 1, "logical": 2, "emotional": 3}
        return vec[idx.get(sense_type, 0)]

    def _compute_weight(self, npc_name: str, event: str,
                        access_count: int = 1, importance: float = 0.5,
                        emotion: float = 0.3, days_old: float = 0) -> float:
        """六因子权重公式"""
        F = min(1.0, __import__('math').log2(access_count + 1) / __import__('math').log2(20))
        I = importance
        E = emotion
        R = max(0, 1.0 - days_old / 90)  # 今天1.0，90天≈0
        sense_type = self._detect_sense_type(event)
        S = self._get_sense_match(npc_name, sense_type)
        X = 1.5 if self._detect_expertise(npc_name, event) else 0
        noise = __import__('random').uniform(-0.05, 0.05)
        W = (self.W_FREQ * F + self.W_IMP * I + self.W_EMO * E +
             self.W_RECENCY * R + self.W_SENSE * S + self.W_EXPERTISE * X + noise)
        return max(0, min(1.0, W))

    def _daily_decay(self, evt: dict, game_day: int) -> float:
        """指数衰减，越老的记忆衰减越慢"""
        if evt.get("fixed"):
            return evt.get("weight", 0.5)
        create_day = evt.get("create_day", game_day)
        age = max(0, game_day - create_day)
        age_factor = min(1.0, age / 30)
        rate = self.GAMMA_BASE + age_factor * self.GAMMA_AGE_SLOPE
        new_w = evt.get("weight", 0.5) * rate
        return max(0, new_w)

    def _check_consolidate(self, evt: dict) -> bool:
        """检查是否满足固化条件"""
        if evt.get("fixed"):
            return True
        ac = evt.get("access_count", 0)
        if ac >= self.FIXED_THRESHOLD:
            return True
        ei = evt.get("emo_imp_product", 0)
        if ei > self.FIXED_EMO_IMP and ac >= 2:
            return True
        return False

    # ── 新记忆事件存储格式 ──────────────────────────────────
    # {
    #   "event": "玩家帮找打狗棒",
    #   "date": "2026-06-01T10:30:00",
    #   "sense_type": "logical",
    #   "importance": 0.8,
    #   "emotion": 0.6,
    #   "weight": 0.72,
    #   "access_count": 3,
    #   "last_access": "2026-06-02T14:00:00",
    #   "fixed": false,
    #   "source": "player",
    #   "tags": ["洪七公", "打狗棒", "丐帮"],
    #   "create_day": 1,
    #   "confidence": 1.0
    # }

    def update_longterm(self, npc_name: str, event: str, layer: str = None,
                        fixed_layer: bool = None):
        """添加一条经历层记忆（新权重公式 + 感官/专业匹配）
        兼容旧调用：layer/fixed_layer 参数仍接受但不再主导
        """
        ltf = self.base / "longterm" / f"{npc_name}_summary.json"
        data: dict = _read_json(ltf)
        if not data:
            data = {"npc_name": npc_name, "summary": "", "key_events": []}
        events = data["key_events"]
        now = now_iso()
        game_day = getattr(self, '_game_day', 0)
        self._game_day = game_day + 1

        # 已有相同事件 → access_count + weight
        for e in events:
            if e["event"] == event:
                if not e.get("fixed", False):
                    e["access_count"] = e.get("access_count", 0) + 1
                    e["last_access"] = now
                    imp = e.get("importance", 0.5)
                    emo = e.get("emotion", 0.3)
                    days_old = max(0, game_day - e.get("create_day", 0))
                    e["weight"] = self._compute_weight(
                        npc_name, event, e["access_count"], imp, emo, days_old)
                    e["fixed"] = self._check_consolidate(e)
                data["last_updated"] = now
                _write_json(ltf, data)
                return

        # 新记忆：自动判断各字段
        sense_type = self._detect_sense_type(event)
        importance = 0.8 if any(kw in event for kw in
                                ["击杀", "任务", "秘籍", "决战", "九阴", "突破"]) else 0.4
        emotion = 0.7 if any(kw in event for kw in
                             ["愤怒", "伤心", "高兴", "背叛", "感动", "怕"]) else 0.3
        weight = self._compute_weight(npc_name, event, 1, importance, emotion, 0)
        fixed = fixed_layer or (self._check_consolidate({
            "access_count": 1, "emo_imp_product": importance * emotion, "fixed": False})
            if importance * emotion > 0.6 else False)

        new_mem = {
            "event": event,
            "date": now,
            "sense_type": sense_type,
            "importance": importance,
            "emotion": emotion,
            "weight": weight,
            "access_count": 1,
            "last_access": now,
            "fixed": fixed,
            "source": "player",
            "tags": [],
            "create_day": game_day,
            "confidence": 1.0,
        }
        events.append(new_mem)

        # 压力衰减
        self._apply_pressure(npc_name, events)
        data["key_events"] = events
        data["last_updated"] = now
        _write_json(ltf, data)

    def _apply_pressure(self, npc_name: str, events: list):
        """短时间大量写入 → 压力衰减"""
        recent = sum(1 for e in events
                     if e.get("date", "").startswith(now_iso()[:10]))
        rate = recent / 10  # 过去10分钟
        if rate > self.PRESSURE_RATE:
            factor = max(self.PRESSURE_MIN, 1.0 - (rate - self.PRESSURE_RATE) * 0.02)
            for e in events:
                if not e.get("fixed", False):
                    e["weight"] = max(0, e.get("weight", 0.5) * factor)

    def record_references(self, npc_name: str, referenced_events: list) -> None:
        """被检索到的记忆：权重更新 + 衰减"""
        ltf = self.base / "longterm" / f"{npc_name}_summary.json"
        data: dict = _read_json(ltf)
        if not data:
            return
        events = data.get("key_events", [])
        if not events:
            return

        ref_set = set(referenced_events)
        now = now_iso()
        game_day = getattr(self, '_game_day', 0)
        changed = False

        for e in events:
            if e.get("fixed", False):
                continue
            if e["event"] in ref_set:
                e["access_count"] = e.get("access_count", 0) + 1
                e["last_access"] = now
                # 重新计算权重（引用后频次上升）
                imp = e.get("importance", 0.5)
                emo = e.get("emotion", 0.3)
                days_old = max(0, game_day - e.get("create_day", 0))
                e["weight"] = self._compute_weight(
                    npc_name, e["event"], e["access_count"], imp, emo, days_old)
                e["fixed"] = self._check_consolidate(e)
                changed = True
            else:
                # 未引用 → 日常衰减
                new_w = self._daily_decay(e, game_day)
                if new_w != e.get("weight", 0.5):
                    e["weight"] = new_w
                    changed = True

        # 清理遗忘
        events = [e for e in events
                  if e.get("fixed", False) or e.get("weight", 0) > 0.1]
        data["key_events"] = events

        if changed:
            data["last_updated"] = now
            _write_json(ltf, data)

    def get_longterm(self, npc_name: str) -> dict:
        """获取经历层记忆 — 按 Score 排序输出"""
        ltf = self.base / "longterm" / f"{npc_name}_summary.json"
        data: dict = _read_json(ltf)
        if not data:
            return {"npc_name": npc_name, "summary": "", "key_events": []}

        events = data.get("key_events", [])
        # 按权重降序排列
        events.sort(key=lambda x: -x.get("weight", 0))
        data["key_events"] = events
        return data

    # ── 旧接口兼容包装 ──────────────────────────────────────
    WEIGHT_RARE = 0.6
    WEIGHT_UNCOMMON = 0.3
    FIXED_RARE = set()

    def _classify_event(self, event: str) -> tuple:
        return ("uncommon", False)

    def _compute_effective_weight(self, evt: dict) -> float:
        return evt.get("weight", 0.5)

    def _recalc_layer(self, evt: dict, effective_weight: float) -> str:
        return evt.get("layer", "uncommon")

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
