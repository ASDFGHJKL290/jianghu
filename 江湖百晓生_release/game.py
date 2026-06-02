# -*- coding: utf-8 -*-
"""
game.py — 江湖百晓生 v2.0
业务逻辑层：数据定义 + 全局状态 + 持久化 + 战斗 + 新手引导
由 main.py 拆分而来，main.py 只保留 HTTP 路由层
"""

import os
import json as _json
import random
import time
from pydantic import BaseModel, Field
from typing import Optional

# ════════════════════════════════════════════════
# 路径
# ════════════════════════════════════════════════
BASE_DIR  = os.path.dirname(os.path.abspath(__file__))
STATE_DIR = os.path.join(BASE_DIR, "state")
HIST_DIR  = os.path.join(STATE_DIR, "histories")
os.makedirs(STATE_DIR, exist_ok=True)
os.makedirs(HIST_DIR,  exist_ok=True)

PLAYER_FILE  = os.path.join(STATE_DIR, "player.json")
EMOTION_FILE = os.path.join(STATE_DIR, "emotions.json")
CHAT_MSG_FILE = os.path.join(STATE_DIR, "chat_messages.json")

# ════════════════════════════════════════════════
# 数据：修为境界
# ════════════════════════════════════════════════
REALMS = [
    {"level": 1, "name": "初入江湖", "cum": 0,    "title": "江湖新秀"},
    {"level": 2, "name": "初窥门径", "cum": 100,  "title": "江湖少侠"},
    {"level": 3, "name": "小有所成", "cum": 400,  "title": "江湖侠客"},
    {"level": 4, "name": "融会贯通", "cum": 1000, "title": "一方高手"},
    {"level": 5, "name": "一代宗师", "cum": 2000, "title": "武林名宿"},
    {"level": 6, "name": "登峰造极", "cum": 4000, "title": "绝顶强者"},
    {"level": 7, "name": "天下无敌", "cum": 8000, "title": "传说"},
]

def get_realm_info(total_exp: int) -> dict:
    current = REALMS[0]
    for r in REALMS:
        if total_exp >= r["cum"]:
            current = r
        else:
            break
    idx = current["level"] - 1
    next_r = REALMS[idx + 1] if idx < len(REALMS) - 1 else None
    if next_r is None:
        progress = 100.0; need = 0; progress_exp = 0
    else:
        need = next_r["cum"] - current["cum"]
        progress_exp = total_exp - current["cum"]
        progress = min(100.0, progress_exp / need * 100) if need > 0 else 100.0
    return {
        "level": current["level"], "name": current["name"], "title": current["title"],
        "total_exp": total_exp, "progress_exp": progress_exp,
        "need": need, "progress": round(progress, 1),
        "next": next_r["name"] if next_r else None,
        "next_title": next_r["title"] if next_r else None,
        "is_max": idx >= len(REALMS) - 1,
    }

# ════════════════════════════════════════════════
# 数据：门派配置
# ════════════════════════════════════════════════
FACTION_CONFIG = {
    "少林": {
        "name": "少林派",
        "desc": "武林正宗，武学根基。天下武功出少林，少林弟子以易筋经、洗髓经名震江湖。",
        "bonus": "初始武力+5，少林系NPC初始好感+10",
        "initial_items": [{"name": "少林基础拳谱", "icon": "📖", "count": 1}],
        "npc_bonus": {"扫地僧": 10},
    },
    "武当": {
        "name": "武当派",
        "desc": "以柔克刚，内家功夫登峰造极。武当剑法绵延不绝，太极拳圆转如意。",
        "bonus": "初始内力+5，武当系NPC初始好感+10",
        "initial_items": [{"name": "武当基础剑谱", "icon": "📖", "count": 1}],
        "npc_bonus": {},
    },
    "丐帮": {
        "name": "丐帮",
        "desc": "天下第一大帮，打狗棒法、降龙十八掌威震武林。帮众遍天下，消息最灵通。",
        "bonus": "初始敏捷+5，店小二初始好感+15",
        "initial_items": [{"name": "打狗棒法入门", "icon": "📖", "count": 1}],
        "npc_bonus": {"店小二": 15},
    },
    "无门派": {
        "name": "江湖散人",
        "desc": "不属于任何门派，云游四方，广结善缘。自由度最高，可自创武学。",
        "bonus": "初始银两+10，无门派限制",
        "initial_items": [],
        "npc_bonus": {},
    },
}

# ════════════════════════════════════════════════
# 数据：商店与道具
# ════════════════════════════════════════════════


game_day:      int = 1
silver:        int = 15
exp:           int = 0
player_items:  list = []
tutorial_step: int = 0
faction:       str = ""
last_work_day: int = 0  # 上次打工的游戏日（防刷）

# 由 refactor 拆分：战斗逻辑在 combat.py，商店在 shop.py，引导在 tutorial.py
from combat import combat_state, combat_narrative, _bind_game_vars, combat_start, combat_action
from shop import SHOP_ITEMS, ITEM_EFFECTS
from tutorial import tutorial_start, tutorial_complete_step, tutorial_status, TUTORIAL_COMPLETE_GUIDE

# 对话历史 {key: list}  key="npc|uid"
histories: dict = {}

# 前端聊天记录持久化 {npc_name: [messages]}
chat_messages: dict = {}

# 外部注入
chat = None  # JianghuChat 实例，由 main.py 注入
last_activity: dict = {}
MAX_HIST = 15

# ════════════════════════════════════════════════
# 持久化
# ════════════════════════════════════════════════
def _jload(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return _json.load(f)
    except (FileNotFoundError, _json.JSONDecodeError):
        return None

def _jsave(path, data):
    try:
        with open(path, "w", encoding="utf-8") as f:
            _json.dump(data, f, ensure_ascii=False, indent=2)
        return True
    except Exception:
        return False

def _hist_path(npc: str, uid: str) -> str:
    safe = f"{npc}_{uid}".replace("/", "_").replace("\\", "_")
    return os.path.join(HIST_DIR, f"{safe}.json")

def _hist_key(npc: str, uid: str) -> str:
    return f"{npc}|{uid}"

def load_all_state():
    """启动时恢复玩家数据"""
    global game_day, silver, exp, player_items, tutorial_step, faction, last_work_day
    data = _jload(PLAYER_FILE)
    if data:
        game_day      = data.get("game_day", 1)
        silver        = data.get("silver", 15)
        exp           = data.get("exp", 0)
        player_items  = data.get("player_items", [])
        # 自动补全缺失的 icon 字段（防止旧存档或 bug 导致图标丢失）
        _ITEM_ICON_MAP = {
            "女儿红": "\U0001f376", "碎银": "\U0001f4b0", "小菜拼盘": "\U0001f968",
            "大还丹": "\U0001f48a", "包子": "\U0001f95f", "醒酒汤": "\U0001f375",
            "叫花鸡": "\U0001f357", "烧饼": "\U0001f9ed", "狗肉": "\U0001f356",
            "佛珠": "\U0001f4ff", "药膏": "\U0001f9f4", "菩提子": "\U0001f4ff",
            "剑谱残页": "\U0001f4d6", "指南针": "\U0001f9ed", "青钢剑": "\U0001f5e1\ufe0f",
            "花瓣": "\U0001f338", "玉箫": "\U0001f3b5",
        }
        for _it in player_items:
            if not _it.get("icon"):
                _it["icon"] = _ITEM_ICON_MAP.get(_it.get("name",""), "\U0001f381")
        tutorial_step = data.get("tutorial_step", 0)
        faction       = data.get("faction", "")
        last_work_day = data.get("last_work_day", 0)
        if chat:
            for uid, quests in data.get("active_quests", {}).items():
                chat.active_quests[uid] = quests
            for uid, completed in data.get("quest_completion", {}).items():
                chat.quest_completion[uid] = completed
            # 加载任务进度（completed_steps 数组）
            quest_progress_data = data.get("quest_progress", {})
            if quest_progress_data:
                chat.quest_progress = quest_progress_data
            # 加载章节进度
            chapter_progress = data.get("chapter_progress", {})
            if chapter_progress:
                chat.chapter_progress = chapter_progress
    em_data = _jload(EMOTION_FILE)
    if em_data and chat:
        chat.emotion_engine._history = em_data.get("history", {})
    # 加载前端聊天记录
    chat_data = _jload(CHAT_MSG_FILE)
    if chat_data:
        global chat_messages
        chat_messages = chat_data
    for fname in os.listdir(HIST_DIR):
        fpath = os.path.join(HIST_DIR, fname)
        fdata = _jload(fpath)
        if fdata and isinstance(fdata, dict) and "history" in fdata:
            npc = fdata.get("npc", "")
            uid = fdata.get("uid", "default")
            if npc and isinstance(fdata["history"], list):
                histories[_hist_key(npc, uid)] = fdata["history"]

    # 绑定战斗模块（让 combat.py 共享 exp 引用）
    from combat import _bind_game_vars
    _bind_game_vars(exp, get_realm_info)

    # 绑定战斗模块（避免循环 import）


def save_chat_messages():
    """仅保存聊天记录（比 save_all_state 轻量）"""
    _jsave(CHAT_MSG_FILE, chat_messages)

def save_all_state():
    """运行时随时保存"""
    if chat is None:
        return
    player_data = {
        "game_day":         game_day,
        "silver":           silver,
        "exp":              exp,
        "tutorial_step":    tutorial_step,
        "faction":          faction,
        "active_quests":    chat.active_quests,
        "quest_completion": chat.quest_completion,
        "quest_progress":   chat.quest_progress,
        "chapter_progress": chat.chapter_progress,
        "player_items":     player_items,
        "last_work_day":    last_work_day,
    }
    _jsave(PLAYER_FILE, player_data)
    _jsave(EMOTION_FILE, {"history": chat.emotion_engine._history})
    _jsave(CHAT_MSG_FILE, chat_messages)
    for key, h in histories.items():
        npc, uid = key.split("|", 1) if "|" in key else (key, "default")
        _jsave(_hist_path(npc, uid), {"npc": npc, "uid": uid, "history": h})

# ════════════════════════════════════════════════
# 辅助函数
# ════════════════════════════════════════════════
def get_map_fragment_count() -> int:
    return sum(it.get("count", 1) for it in player_items if "地图碎片" in it.get("name", ""))

def try_work_at_tavern() -> int | None:
    """店小二打工：每天限1次，返回银两数或None（冷却中）"""
    global last_work_day, silver
    if last_work_day >= game_day:
        return None
    import random
    reward = random.randint(10, 15)
    silver += reward
    last_work_day = game_day
    return reward

def get_unlocked_locations() -> list:
    """根据图碎数量返回已解锁地点"""
    cnt = get_map_fragment_count()
    base = ["悦来酒楼", "武林盟主府", "天涯海角"]
    if cnt >= 1:  base.append("少林寺")
    if cnt >= 2:  base.append("丐帮总舵")
    if cnt >= 3:  base.append("华山思过崖")
    if cnt >= 4:  base.append("桃花岛")
    if cnt >= 5:  base.append("四川唐门")
    if cnt >= 6:  base.append("黑木崖")
    if cnt >= 7:  base.append("日月神教")
    if cnt >= 8:  base.append("白驼山庄")
    if cnt >= 9:  base.append("黑龙潭")
    if cnt >= 10: base.append("江湖游医")
    seen = set(); result = []
    for loc in base:
        if loc not in seen:
            seen.add(loc); result.append(loc)
    return result

# ════════════════════════════════════════════════
# Pydantic 模型
# ════════════════════════════════════════════════
class ChatReq(BaseModel):
    message:  str = Field(..., min_length=1, max_length=500)
    npc_name: str = Field(default="店小二")
    user_id:  str = Field(default="default")

class ClearReq(BaseModel):
    npc_name: str

class AbandonReq(BaseModel):
    qid:     str
    user_id: str = "default"

class CombatReq(BaseModel):
    action:   str
    npc_name: str = "店小二"
    user_id:  str = "default"

class ShopBuyReq(BaseModel):
    item_name: str
    count:     int = 1

class TutorialStartReq(BaseModel):
    faction: str

class TutorialStepReq(BaseModel):
    action: str
    value:  str = ""

class MailboxReadReq(BaseModel):
    message_ids: list
    user_id:     str = "default"

class MailboxSendReq(BaseModel):
    npc_name: str
    user_id:  str = "default"

# ════════════════════════════════════════════════
# 战斗逻辑
# ════════════════════════════════════════════════


def get_hist(npc: str, uid: str) -> list:
    return histories.get(_hist_key(npc, uid), [])

def set_hist(npc: str, uid: str, h: list):
    histories[_hist_key(npc, uid)] = h

def update_activity(npc: str, uid: str):
    """更新最后活跃时间，触发情感衰减"""
    key = _hist_key(npc, uid)
    now = time.time()
    last = last_activity.get(key, 0)
    if now - last > 60 and chat:
        chat.emotion_engine.decay(npc, now - last)
    last_activity[key] = now


# ════════════════════════════════════════════════
# 邮箱系统
# ════════════════════════════════════════════════
MAILBOX_FILE = os.path.join(STATE_DIR, "mailbox.json")

def _load_mailbox() -> dict:
    """加载邮箱数据（per-user）"""
    if not os.path.exists(MAILBOX_FILE):
        return {}
    try:
        with open(MAILBOX_FILE, "r", encoding="utf-8") as f:
            return _json.load(f)
    except (_json.JSONDecodeError, IOError):
        return {}

def _save_mailbox(data: dict):
    with open(MAILBOX_FILE, "w", encoding="utf-8") as f:
        _json.dump(data, f, ensure_ascii=False)

def get_mailbox(user_id: str = "default") -> list:
    """获取用户邮箱消息列表"""
    data = _load_mailbox()
    return data.get(user_id, [])

def add_mail_message(user_id: str, from_npc: str, content: str, mood: str = "",
                      chain_id: str = "", step: int = 0, total_steps: int = 0,
                      action_link: dict = None):
    """添加一条邮箱消息
    chain_id: 事件链ID, 同一链同一NPC的未读消息自动聚合（更新而不是新增）
    step/total_steps: 在链中的位置
    action_link: {"type":"npc"|"location", "target":"NPC名"|"地点名", "label":"按钮文字"}
    返回: True=已添加, False=邮箱满被拦截
    """
    import uuid
    data = _load_mailbox()
    msgs = data.setdefault(user_id, [])

    # 邮箱满15条未读 → 暂停推送，不丢弃（玩家清一清就会恢复）
    unread = sum(1 for m in msgs if not m.get("read", False))
    if unread >= 15:
        return False

    # 聚合：同一chain_id同一from_npc的最近一条未读消息，更新内容而不是新增
    if chain_id:
        for existing in reversed(msgs):
            if (existing.get("chain_id") == chain_id
                    and existing.get("from_npc") == from_npc
                    and not existing.get("read", False)):
                existing["content"] = content
                existing["mood"] = mood or existing.get("mood", "平静")
                existing["timestamp"] = time.strftime("%Y-%m-%dT%H:%M:%S")
                existing["step"] = step
                existing["total_steps"] = total_steps
                if action_link:
                    existing["action_link"] = action_link
                _save_mailbox(data)
                return True

    msg = {
        "id": f"msg_{uuid.uuid4().hex[:8]}",
        "from_npc": from_npc,
        "content": content,
        "mood": mood or "平静",
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "read": False,
    }
    if chain_id:
        msg["chain_id"] = chain_id
        msg["step"] = step
        msg["total_steps"] = total_steps
    if action_link:
        msg["action_link"] = action_link
    msgs.append(msg)
    # 最多保留50条
    if len(msgs) > 50:
        msgs = msgs[-50:]
    data[user_id] = msgs
    _save_mailbox(data)
    return True

def mark_mail_read(user_id: str, message_ids: list):
    """标记消息为已读"""
    data = _load_mailbox()
    msgs = data.get(user_id, [])
    id_set = set(message_ids)
    for m in msgs:
        if m["id"] in id_set:
            m["read"] = True
    data[user_id] = msgs
    _save_mailbox(data)

def delete_mail_message(user_id: str, message_ids: list):
    """删除指定消息"""
    data = _load_mailbox()
    msgs = data.get(user_id, [])
    id_set = set(message_ids)
    data[user_id] = [m for m in msgs if m["id"] not in id_set]
    _save_mailbox(data)

def unread_mail_count(user_id: str = "default") -> int:
    """获取未读消息数量"""
    data = _load_mailbox()
    return sum(1 for m in data.get(user_id, []) if not m.get("read", False))

def get_read_mail_npcs(user_id: str = "default") -> set:
    """获取玩家已读飞鸽中涉及的NPC集合（from_npc + 消息正文中提名的NPC）
    用于事件路由：玩家已知哪些NPC有动静，影响后续剧情节点选择"""
    from npc_data import NPC_PROFILES
    data = _load_mailbox()
    npcs = set()
    for m in data.get(user_id, []):
        if not m.get("read", False):
            continue
        sender = m.get("from_npc", "")
        if sender:
            npcs.add(sender)
        # 从正文中提取提到的NPC名
        content = m.get("content", "")
        for npc_name in NPC_PROFILES:
            if npc_name != sender and len(npc_name) > 1 and npc_name in content:
                npcs.add(npc_name)
    return npcs
