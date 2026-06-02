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
SHOP_ITEMS = {
    "江湖地图碎片": {"price": 30, "icon": "🧩", "desc": "收集碎片解锁新地点"},
    "大还丹":       {"price": 20, "icon": "💊", "desc": "恢复30点气血"},
    "女儿红":       {"price": 15, "icon": "🍶", "desc": "赠予店小二增加10点好感度"},
    "碎银":         {"price": 10, "icon": "💰", "desc": "5两碎银，可用于打赏"},
}

ITEM_EFFECTS = {
    "大还丹": {"type": "hp",    "value": 30, "desc": "恢复30点气血"},
    "女儿红": {"type": "favor", "target": "店小二", "value": 10, "desc": "增加10点好感度"},
    "青钢剑": {"type": "equip", "value": 10, "desc": "装备后战斗伤害+10%"},
    "碎银":   {"type": "silver","value": 5,  "desc": "5两碎银"},
}

# ════════════════════════════════════════════════
# 全局状态变量
# ════════════════════════════════════════════════
game_day:      int = 1
silver:        int = 15
exp:           int = 0
player_items:  list = []
tutorial_step: int = 0
faction:       str = ""

# 战斗状态 {npc_name: {...}}
combat_state: dict = {}

# 对话历史 {key: list}  key="npc|uid"
histories: dict = {}

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
    global game_day, silver, exp, player_items, tutorial_step, faction
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
    for fname in os.listdir(HIST_DIR):
        fpath = os.path.join(HIST_DIR, fname)
        fdata = _jload(fpath)
        if fdata and isinstance(fdata, dict) and "history" in fdata:
            npc = fdata.get("npc", "")
            uid = fdata.get("uid", "default")
            if npc and isinstance(fdata["history"], list):
                histories[_hist_key(npc, uid)] = fdata["history"]

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
    }
    _jsave(PLAYER_FILE, player_data)
    _jsave(EMOTION_FILE, {"history": chat.emotion_engine._history})
    for key, h in histories.items():
        npc, uid = key.split("|", 1) if "|" in key else (key, "default")
        _jsave(_hist_path(npc, uid), {"npc": npc, "uid": uid, "history": h})

# ════════════════════════════════════════════════
# 辅助函数
# ════════════════════════════════════════════════
def get_map_fragment_count() -> int:
    return sum(it.get("count", 1) for it in player_items if "地图碎片" in it.get("name", ""))

def get_unlocked_locations() -> list:
    """根据图碎数量返回已解锁地点"""
    cnt = get_map_fragment_count()
    base = ["悦来酒楼", "武林盟主府"]
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

# ════════════════════════════════════════════════
# 战斗逻辑
# ════════════════════════════════════════════════
def combat_start(npc_name: str) -> dict:
    enemy_name = npc_name  # 用当前NPC作为对手
    combat_state[npc_name] = {
        "player_hp": 100, "enemy_hp": 80, "enemy_max": 80,
        "status": "ongoing", "enemy_name": enemy_name, "round": 0,
    }
    npc_openings = {
        "店小二":   "（店小二把抹布往肩上一甩，挽起袖子）客官，别看小的端盘子，当年在镖局也练过几手！来来来，咱们切磋切磋！",
        "武林盟主": "（萧千秋眼中精光一闪，缓缓站起）壮士，既然你有心比试，本座便陪你走几招。出手吧！",
        "神秘大侠": "（神秘大侠嘴角微扬，手指轻轻转动酒杯）哦？要动手？……那就来吧。",
        "扫地僧": "（扫地僧停下手中扫帚，缓缓抬头）施主执意要战？……阿弥陀佛，贫僧便以佛法化干戈吧。请。",
        "洪七公": "（洪七公啃了一口鸡腿，抹了抹嘴上的油）嘿嘿，要跟老叫化比划？先让老叫化吃完这只鸡再说！接招——降龙十八掌！",
        "风清扬": "（风清扬负手而立，衣袂飘飞）年轻人，要学独孤九剑？那得先看看你有没有这个命。来吧，出招。",
        "黄衫女": "（黄衫女素手轻扬，古琴弦音骤然一紧）阁下非要逼我出手？……既如此，莫怪琴音无情了。",
        "唐巧": "（唐巧面无表情，指尖已扣住数枚毒针）你确定要跟我动手？唐门的暗器，可从不出空。",
        "任盈盈": "（任盈盈冷笑一声，玉箫横在唇边）哼，不自量力。那就让你见识一下日月神教的手段。",
        "任我行": "（任我行仰天长笑，气势如虹）哈哈哈哈！好胆量！敢与本座动手，你也配？！吸星大法伺候！",
        "欧阳克": "（欧阳克折扇轻摇，嘴角勾起阴笑）哟，想找死？本公子成全你。蛇杖伺候！",
        "瑛姑": "（瑛姑眼中杀气腾腾，双手泛起寒光）你来做什么？！是不是他派你来的？！说！！",
        "平一指": "（平一指推了推眼镜，冷冷道）要我动手？阎王叫人三更死，谁敢留人到五更。你自己选个死法吧。",
    }
    opening = npc_openings.get(npc_name,
        f"突然，一道黑影从暗处跃出！{enemy_name}拦住了你的去路。\n\n他冷笑道：「此路不通，留下买路财！」")
    return {
        "status": "started", "enemy_name": enemy_name,
        "player_hp": 100, "enemy_hp": 80,
        "opening_text": opening, "realm": get_realm_info(exp),
    }

def combat_action(req_action: str, npc_name: str) -> dict:
    global exp
    if npc_name not in combat_state:
        raise ValueError("未在战斗状态")
    state = combat_state[npc_name]
    ph = state["player_hp"]
    eh = state["enemy_hp"]

    # 查看状态：不打战斗，直接返回当前血量描述
    if req_action == "status":
        realm_info = get_realm_info(exp)
        reply = (
            f"【当前战况】\n"
            f"· 你的生命：{ph}/100（{realm_info['name']}）\n"
            f"· {state['enemy_name']}的生命：{eh}/{state.get('enemy_max', 80)}\n"
            f"· 回合数：{state['round']}\n"
            f"· 当前状态：{'势均力敌' if abs(ph - eh) < 20 else ('你占上风' if ph > eh else '你处下风')}"
        )
        return {"combat_result": {"hp": ph, "enemy_hp": eh, "status": "ongoing"},
                "player_hp": ph, "enemy_hp": eh, "status": "ongoing",
                "reply": reply, "exp": exp, "realm": realm_info}

    if req_action == "retreat":
        hp_adv = ph - eh
        if hp_adv > 20:
            can_escape = True
            retreat_desc = "你虚晃一招，纵身跃出战圈，头也不回地撤走了！敌人追赶不及，只能望着你的背影怒喝。"
        elif hp_adv < -20:
            can_escape = (hash((ph * 7 + eh * 3)) % 10) < 2
            retreat_desc = "你拼尽全力甩开敌人的攻势，勉强脱身而出！" if can_escape else "你试图撤退，却被敌人死死缠住！"
        else:
            can_escape = (hash((ph * 7 + eh * 3)) % 10) < 5
            retreat_desc = "你寻隙脱身，成功脱离了战斗！" if can_escape else "撤退不成！敌人趁机发动猛攻！"

        if can_escape:
            state["status"] = "escape"; del combat_state[npc_name]
            return {"combat_result": {"hp": ph, "enemy_hp": eh, "status": "escape", "retreat_desc": retreat_desc},
                    "player_hp": ph, "enemy_hp": eh, "status": "escape", "exp": exp, "realm": get_realm_info(exp)}
        else:
            damage = random.randint(15, 25)
            new_ph = max(0, ph - damage)
            state["player_hp"] = new_ph; state["round"] += 1
            state["status"] = "ongoing" if new_ph > 0 else "defeat"
            if new_ph == 0: del combat_state[npc_name]
            return {"combat_result": {"hp": new_ph, "enemy_hp": eh, "status": state["status"],
                                     "player_dmg": damage, "enemy_dmg": 0, "retreat_desc": retreat_desc},
                    "player_hp": new_ph, "enemy_hp": eh, "status": state["status"],
                    "exp": exp, "realm": get_realm_info(exp)}

    # attack / trick
    player_dmg = random.randint(18, 28)
    enemy_dmg  = random.randint(10, 20)
    if req_action == "trick":
        player_dmg = int(player_dmg * 1.4); enemy_dmg = int(enemy_dmg * 0.6)

    new_eh = max(0, eh - player_dmg)
    new_ph = max(0, ph - enemy_dmg)
    state["player_hp"] = new_ph; state["enemy_hp"] = new_eh; state["round"] += 1

    if new_eh <= 0:
        state["status"] = "victory"; victory_exp = random.randint(15, 25)
        old_realm = get_realm_info(exp)
        exp += victory_exp
        new_realm = get_realm_info(exp)
        breakthrough = new_realm["level"] > old_realm["level"]
        del combat_state[npc_name]
        return {"combat_result": {"hp": new_ph, "enemy_hp": 0, "status": "victory",
                                 "player_dmg": player_dmg, "enemy_dmg": enemy_dmg,
                                 "exp_gained": victory_exp, "breakthrough": breakthrough,
                                 "new_realm": new_realm},
                "player_hp": new_ph, "enemy_hp": 0, "status": "victory",
                "exp": exp, "realm": new_realm,
                "breakthrough": {"old_name": old_realm["name"], "new_name": new_realm["name"]} if breakthrough else None}

    if new_ph <= 0:
        state["status"] = "defeat"; del combat_state[npc_name]
        return {"combat_result": {"hp": 0, "enemy_hp": new_eh, "status": "defeat",
                                 "player_dmg": player_dmg, "enemy_dmg": enemy_dmg},
                "player_hp": 0, "enemy_hp": new_eh, "status": "defeat",
                "exp": exp, "realm": get_realm_info(exp)}

    state["status"] = "ongoing"
    return {"combat_result": {"hp": new_ph, "enemy_hp": new_eh, "status": "ongoing",
                             "player_dmg": player_dmg, "enemy_dmg": enemy_dmg},
            "player_hp": new_ph, "enemy_hp": new_eh, "status": "ongoing",
            "exp": exp, "realm": get_realm_info(exp)}

# ════════════════════════════════════════════════
# 新手引导逻辑
# ════════════════════════════════════════════════

# 新手引导完成后的玩家指引
TUTORIAL_COMPLETE_GUIDE = """📍 新手引导完成！接下来你可以：

🏛️ 前往【武林盟主府】—— 武林盟主会告诉你江湖大势，接取主线任务
🍜 前往【丐帮总舵】—— 洪七公正在物色传人，打狗棒法等着你
⛰️ 前往【华山思过崖】—— 风清扬隐居于此，或许愿意指点你几招

💡 提示：点击左侧地图图标可以切换地点，与各路高手交谈可触发更多任务！"""

def tutorial_status() -> dict:
    result = {
        "step": tutorial_step,
        "faction": faction,
        "is_complete": tutorial_step >= 7,
        "map_fragment_count": get_map_fragment_count(),
    }
    # 如果新手引导已完成，返回完成指引
    if tutorial_step >= 7:
        result["complete_guide"] = TUTORIAL_COMPLETE_GUIDE
    return result

def tutorial_start(req_faction: str, user_id: str = "default") -> dict:
    global tutorial_step, faction, player_items
    if req_faction not in FACTION_CONFIG:
        raise ValueError("非法门派")
    fc = FACTION_CONFIG[req_faction]
    faction = req_faction
    for it in fc.get("initial_items", []):
        ex = next((p for p in player_items if p["name"] == it["name"]), None)
        if ex: ex["count"] += it["count"]
        else: player_items.append(dict(it))
    rel_path = os.path.join(STATE_DIR, "relations", f"{user_id}.json")
    os.makedirs(os.path.dirname(rel_path), exist_ok=True)
    rel_data = _jload(rel_path) if os.path.exists(rel_path) else {}
    user_rel = rel_data.get(user_id, {})
    for npc_name, bonus in fc.get("npc_bonus", {}).items():
        if npc_name not in user_rel:
            user_rel[npc_name] = {"intimacy": 30, "know_level": 1}
        user_rel[npc_name]["intimacy"] = min(100, user_rel[npc_name]["intimacy"] + bonus)
    rel_data[user_id] = user_rel
    _jsave(rel_path, rel_data)
    tutorial_step = 2
    save_all_state()
    return {
        "step": tutorial_step, "faction": faction,
        "reply": (
            f"「{fc['name']}」弟子，久仰大名！\n{fc['desc']}\n\n"
            "📜 **新手指引：**\n\n我是店小二，这悦来酒楼便是你闯荡江湖的第一站。\n\n"
            "想要在这江湖立足，你得先通过我的考验——完成【初入江湖】任务。\n\n"
            "你可以问我以下话题来推进任务：\n"
            "• 「江湖规矩」——了解江湖基本礼数\n"
            "• 「哪个门派」——了解各大门派情况\n"
            "• 「我的志向」——告诉我你想成为什么样的人\n\n"
            "💡 直接在下方输入框打字跟我聊就行，或者点击下方的快捷按钮。"
        ),
        "faction_bonus": fc["bonus"],
        "silver": silver, "exp": exp,
        "realm": get_realm_info(exp), "player_items": player_items,
    }

def tutorial_complete_step(req_action: str) -> dict:
    global tutorial_step, exp
    if req_action == "step2_done":
        tutorial_step = 3; save_all_state()
        return {"step": tutorial_step}
    if req_action == "tutorial_done":
        tutorial_step = 7; save_all_state()
        return {"step": tutorial_step, "done": True}
    if req_action == "gift_success" and tutorial_step == 5:
        tutorial_step = 6; save_all_state()
        return {"step": tutorial_step}
    if req_action == "combat_won" and tutorial_step == 4:
        exp += 10; tutorial_step = 5; save_all_state()
        return {
            "step": tutorial_step,
            "message": "💰 教学战斗奖励：修为+10\n📍 下一步：将【女儿红】赠送给店小二",
            "exp": exp, "realm": get_realm_info(exp),
        }
    return {"step": tutorial_step}

# ════════════════════════════════════════════════
# 对话历史管理（供 main.py 路由调用）
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
