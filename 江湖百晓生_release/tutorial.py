# -*- coding: utf-8 -*-
"""
tutorial.py — 江湖百晓生 v2.0 新手引导
由 game.py 拆分而来

注意：本模块重度依赖 game.py 的全局状态，
所有 game 模块变量通过 import game 引用。
"""

import game as _g


def tutorial_start(req_faction: str, user_id: str = "default") -> dict:
    if req_faction not in _g.FACTION_CONFIG:
        raise ValueError("非法门派")
    fc = _g.FACTION_CONFIG[req_faction]
    _g.faction = req_faction
    for it in fc.get("initial_items", []):
        ex = next((p for p in _g.player_items if p["name"] == it["name"]), None)
        if ex:
            ex["count"] += it["count"]
        else:
            _g.player_items.append(dict(it))
    rel_path = _g.os.path.join(_g.STATE_DIR, "relations", f"{user_id}.json")
    _g.os.makedirs(_g.os.path.dirname(rel_path), exist_ok=True)
    rel_data = _g._jload(rel_path) if _g.os.path.exists(rel_path) else {}
    user_rel = rel_data.get(user_id, {})
    for npc_name, bonus in fc.get("npc_bonus", {}).items():
        if npc_name not in user_rel:
            user_rel[npc_name] = {"intimacy": 30, "know_level": 1}
        user_rel[npc_name]["intimacy"] = min(100, user_rel[npc_name]["intimacy"] + bonus)
    rel_data[user_id] = user_rel
    _g._jsave(rel_path, rel_data)
    _g.tutorial_step = 2
    _g.save_all_state()
    return {
        "step": _g.tutorial_step, "faction": _g.faction,
        "reply": (
            f"「{fc['name']}」弟子，久仰大名！\n{fc['desc']}\n\n"
            "📜 新手指引：\n\n"
            "我是店小二，这悦来酒楼便是你闯荡江湖的第一站。\n\n"
            "想要在这江湖立足，你得先通过我的考验——完成【初入江湖】任务。\n\n"
            "你可以问我以下话题来推进任务：\n"
            "• 「江湖规矩」——了解江湖基本礼数\n"
            "• 「哪个门派」——了解各大门派情况\n"
            "• 「我的志向」——告诉我你想成为什么样的人\n\n"
            "💡 直接在下方输入框打字跟我聊就行，或者点击下方的快捷按钮。"
        ),
        "faction_bonus": fc["bonus"],
        "silver": _g.silver, "exp": _g.exp,
        "realm": _g.get_realm_info(_g.exp), "player_items": _g.player_items,
    }


def tutorial_complete_step(req_action: str) -> dict:
    if req_action == "step2_done":
        _g.tutorial_step = 3
        _g.save_all_state()
        return {"step": _g.tutorial_step}
    if req_action == "tutorial_done":
        _g.tutorial_step = 7
        _g.save_all_state()
        return {"step": _g.tutorial_step, "done": True}
    if req_action == "gift_success" and _g.tutorial_step == 5:
        _g.tutorial_step = 6
        _g.save_all_state()
        return {"step": _g.tutorial_step}
    if req_action == "combat_won" and _g.tutorial_step == 4:
        _g.exp += 10
        _g.tutorial_step = 5
        _g.save_all_state()
        return {
            "step": _g.tutorial_step,
            "message": "💰 教学战斗奖励：修为+10\n📍 下一步：将【女儿红】赠送给店小二",
            "exp": _g.exp, "realm": _g.get_realm_info(_g.exp),
        }
    return {"step": _g.tutorial_step}


# ════════════════════════════════════════════════
# 对话历史管理（供 main.py 路由调用）
# ════════════════════════════════════════════════


def tutorial_status() -> dict:
    result = {
        "step": _g.tutorial_step,
        "faction": _g.faction,
        "is_complete": _g.tutorial_step >= 7,
        "map_fragment_count": _g.get_map_fragment_count(),
    }
    if _g.tutorial_step >= 7:
        result["complete_guide"] = TUTORIAL_COMPLETE_GUIDE
    return result


TUTORIAL_COMPLETE_GUIDE = """📍 新手引导完成！接下来你可以：

🏛️ 前往【武林盟主府】—— 武林盟主会告诉你江湖大势，接取主线任务
🍜 前往【丐帮总舵】—— 洪七公正在物色传人，打狗棒法等着你
⛰️ 前往【华山思过崖】—— 风清扬隐居于此，或许愿意指点你几招

💡 提示：点击左侧地图图标可以切换地点，与各路高手交谈可触发更多任务！"""
