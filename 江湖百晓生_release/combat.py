# -*- coding: utf-8 -*-
"""
combat.py — 江湖百晓生 v2.0 战斗系统
由 game.py 拆分而来
"""

import random

# 战斗状态（由 game.py 在运行时注入值）
combat_state: dict = {}
combat_narrative: dict = {}
_exp = 0
_get_realm_info = lambda x: {"name": "初入江湖", "level": 1, "title": "江湖新秀", "total_exp": 0}

def _bind_game_vars(exp_val, realm_fn):
    """由 game.py 启动时调用，绑定 exp 和 get_realm_info"""
    global _exp, _get_realm_info
    _exp = exp_val
    _get_realm_info = realm_fn


def combat_start(npc_name: str) -> dict:
    enemy_name = npc_name  # 用当前NPC作为对手
    from npc_data import NPC_PROFILES
    npc_hp = NPC_PROFILES.get(npc_name, {}).get("base_hp", 80)
    combat_state[npc_name] = {
        "player_hp": 100, "enemy_hp": npc_hp, "enemy_max": npc_hp,
        "status": "ongoing", "enemy_name": enemy_name, "round": 0,
    }
    combat_narrative[npc_name] = []  # 清空之前的战斗叙事
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
    # 保存开场文本（后续传给LLM作为战斗背景）
    combat_narrative[f"{npc_name}_bg"] = opening
    return {
        "status": "started", "enemy_name": enemy_name,
        "player_hp": 100, "enemy_hp": 80,
        "opening_text": opening, "realm": _get_realm_info(_exp),
    }


def combat_action(req_action: str, npc_name: str) -> dict:
    if npc_name not in combat_state:
        raise ValueError("未在战斗状态")
    state = combat_state[npc_name]
    ph = state["player_hp"]
    eh = state["enemy_hp"]

    # 查看状态：不打战斗，直接返回当前血量描述
    if req_action == "status":
        realm_info = _get_realm_info(_exp)
        reply = (
            f"【当前战况】\n"
            f"· 你的生命：{ph}/100（{realm_info['name']}）\n"
            f"· {state['enemy_name']}的生命：{eh}/{state.get('enemy_max', 80)}\n"
            f"· 回合数：{state['round']}\n"
            f"· 当前状态：{'势均力敌' if abs(ph - eh) < 20 else ('你占上风' if ph > eh else '你处下风')}"
        )
        return {"combat_result": {"hp": ph, "enemy_hp": eh, "status": "ongoing"},
                "player_hp": ph, "enemy_hp": eh, "status": "ongoing",
                "reply": reply, "exp": _exp, "realm": realm_info}

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
                    "player_hp": ph, "enemy_hp": eh, "status": "escape", "exp": _exp, "realm": _get_realm_info(_exp)}
        else:
            damage = random.randint(15, 25)
            new_ph = max(0, ph - damage)
            state["player_hp"] = new_ph; state["round"] += 1
            state["status"] = "ongoing" if new_ph > 0 else "defeat"
            if new_ph == 0: del combat_state[npc_name]
            return {"combat_result": {"hp": new_ph, "enemy_hp": eh, "status": state["status"],
                                     "player_dmg": damage, "enemy_dmg": 0, "retreat_desc": retreat_desc},
                    "player_hp": new_ph, "enemy_hp": eh, "status": state["status"],
                    "exp": _exp, "realm": _get_realm_info(_exp)}

    # attack / trick
    player_dmg = random.randint(18, 28)
    enemy_dmg  = random.randint(10, 20)
    if req_action == "trick":
        player_dmg = int(player_dmg * 1.4); enemy_dmg = int(enemy_dmg * 0.6)

    new_eh = max(0, eh - player_dmg)
    new_ph = max(0, ph - enemy_dmg)
    state["player_hp"] = new_ph; state["enemy_hp"] = new_eh; state["round"] += 1

    # 平局判定：双方同时倒下
    if new_eh <= 0 and new_ph <= 0:
        state["status"] = "draw"; del combat_state[npc_name]
        return {"combat_result": {"hp": 0, "enemy_hp": 0, "status": "draw",
                                 "player_dmg": player_dmg, "enemy_dmg": enemy_dmg},
                "player_hp": 0, "enemy_hp": 0, "status": "draw",
                "exp": _exp, "realm": _get_realm_info(_exp)}

    if new_eh <= 0:
        state["status"] = "victory"; victory_exp = random.randint(15, 25)
        old_realm = _get_realm_info(_exp)
        _exp += victory_exp
        new_realm = _get_realm_info(_exp)
        breakthrough = new_realm["level"] > old_realm["level"]
        del combat_state[npc_name]
        return {"combat_result": {"hp": new_ph, "enemy_hp": 0, "status": "victory",
                                 "player_dmg": player_dmg, "enemy_dmg": enemy_dmg,
                                 "exp_gained": victory_exp, "breakthrough": breakthrough,
                                 "new_realm": new_realm},
                "player_hp": new_ph, "enemy_hp": 0, "status": "victory",
                "exp": _exp, "realm": new_realm,
                "breakthrough": {"old_name": old_realm["name"], "new_name": new_realm["name"]} if breakthrough else None}

    if new_ph <= 0:
        state["status"] = "defeat"; del combat_state[npc_name]
        return {"combat_result": {"hp": 0, "enemy_hp": new_eh, "status": "defeat",
                                 "player_dmg": player_dmg, "enemy_dmg": enemy_dmg},
                "player_hp": 0, "enemy_hp": new_eh, "status": "defeat",
                "exp": _exp, "realm": _get_realm_info(_exp)}

    state["status"] = "ongoing"
    return {"combat_result": {"hp": new_ph, "enemy_hp": new_eh, "status": "ongoing",
                             "player_dmg": player_dmg, "enemy_dmg": enemy_dmg},
            "player_hp": new_ph, "enemy_hp": new_eh, "status": "ongoing",
            "exp": _exp, "realm": _get_realm_info(_exp)}
