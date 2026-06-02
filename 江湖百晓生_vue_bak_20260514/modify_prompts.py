#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
修改 prompts.py：
1. 完成 NPC_GIFT_CONFIG
2. 替换 ALL_QUESTS 为新的15任务版本（前3章）
"""

import re

# 读取原文件
with open(r'C:\Users\aaa\PycharmProjects\day25\江湖百晓生_vue\prompts.py', 'r', encoding='utf-8') as f:
    content = f.read()

# 1. 完成 NPC_GIFT_CONFIG（在文件末尾添加缺失的部分）
# 检查 NPC_GIFT_CONFIG 是否完整
if 'NPC_GIFT_CONFIG = {' in content and '}"' not in content:
    # NPC_GIFT_CONFIG 不完整，需要补全
    # 找到 NPC_GIFT_CONFIG 的位置，替换整个字典
    npc_gift_new = '''NPC_GIFT_CONFIG = {
    "店小二": {
        "style": "热情好客，请客喝酒",
        "items": [
            {"name": "女儿红", "icon": "🍶", "prob": 0.3, "cond": "player_sad"},
            {"name": "碎银",   "icon": "💰", "prob": 0.2, "cond": "player_happy"},
            {"name": "小菜拼盘", "icon": "🥘", "prob": 0.15, "cond": "any"},
        ],
        "milestone": {
            20: {"name": "江湖地图碎片", "icon": "🧩", "count": 1},
            40: {"name": "店小二推荐信", "icon": "📜", "count": 1},
            60: {"name": "悦来酒楼贵宾卡", "icon": "🃏", "count": 1},
            80: {"name": "神秘酒壶", "icon": "🍶", "count": 1, "desc": "战斗气血+10%"},
        },
    },
    "洪七公": {
        "style": "豪爽，有好吃的就分享",
        "items": [
            {"name": "叫花鸡", "icon": "🍗", "prob": 0.4, "cond": "player_happy"},
            {"name": "烧饼",   "icon": "🫓", "prob": 0.3, "cond": "any"},
        ],
        "milestone": {
            20: {"name": "打狗棒法入门", "icon": "📖"},
            40: {"name": "降龙十八掌秘籍", "icon": "📖"},
            60: {"name": "丐帮信物", "icon": "🃏"},
            80: {"name": "逍遥游", "icon": "📖", "desc": "洪七公自创武学"},
        },
    },
    "扫地僧": {
        "style": "慈悲为怀，赠药助人",
        "items": [
            {"name": "大还丹", "icon": "💊", "prob": 0.3, "cond": "player_hp_low"},
            {"name": "佛珠",   "icon": "📿", "prob": 0.2, "cond": "any"},
        ],
        "milestone": {
            20: {"name": "菩提子", "icon": "📿", "count": 3},
            40: {"name": "易筋经入门", "icon": "📖"},
            60: {"name": "少林信物", "icon": "🃏"},
            80: {"name": "达摩护身符", "icon": "🛡️", "desc": "防御+15%"},
        },
    },
    "风清扬": {
        "style": "高冷但暗中帮助",
        "items": [
            {"name": "剑谱残页", "icon": "📖", "prob": 0.2, "cond": "quest_done"},
            {"name": "指南针",   "icon": "🧭", "prob": 0.3, "cond": "any"},
        ],
        "milestone": {
            20: {"name": "独孤九剑心得", "icon": "📖"},
            40: {"name": "华山地图", "icon": "🗺️"},
            60: {"name": "思过崖信物", "icon": "🃏"},
            80: {"name": "剑圣传承", "icon": "⚔️", "desc": "剑系伤害+20%"},
        },
    },
    "黄衫女": {
        "style": "清冷中带温柔",
        "items": [
            {"name": "花瓣", "icon": "🌸", "prob": 0.3, "cond": "player_happy"},
            {"name": "药膏", "icon": "🧴", "prob": 0.4, "cond": "player_hp_low"},
        ],
        "milestone": {
            20: {"name": "桃花岛医典", "icon": "📖"},
            40: {"name": "玉箫", "icon": "🎵"},
            60: {"name": "桃花岛信物", "icon": "🃏"},
            80: {"name": "碧海潮生曲谱", "icon": "🎵", "desc": "内力恢复+20%"},
        },
    },
    "任盈盈": {
        "style": "傲娇，嘴上嫌弃但偷偷送",
        "items": [
            {"name": "玉箫", "icon": "🎵", "prob": 0.3, "cond": "quest_done"},
            {"name": "药膏", "icon": "🧴", "prob": 0.3, "cond": "player_hp_low"},
        ],
        "milestone": {
            20: {"name": "黑木崖特产", "icon": "🍵"},
            40: {"name": "日月神教信物", "icon": "🃏"},
            60: {"name": "任盈盈的信", "icon": "💌"},
            80: {"name": "笑傲江湖曲谱", "icon": "🎵", "desc": "全属性+5%"},
        },
    },
    "欧阳克": {
        "style": "阴险，送礼可能是陷阱",
        "items": [
            {"name": "毒酒", "icon": "🍷", "prob": 0.3, "cond": "any", "trap": True},
        ],
        "note": "好感度<30时可能送陷阱道具，玩家使用后扣HP",
    },
    "平一指": {
        "style": "看病后给药",
        "items": [
            {"name": "大还丹",   "icon": "💊", "prob": 0.5, "cond": "player_hp_low"},
            {"name": "解毒丹", "icon": "💊", "prob": 0.4, "cond": "player_poisoned"},
        ],
        "milestone": {
            20: {"name": "平一指的诊断书", "icon": "📋"},
            40: {"name": "百年人参", "icon": "🌿"},
            60: {"name": "江湖游医信物", "icon": "🃏"},
            80: {"name": "生死符", "icon": "💀", "desc": "可控制NPC"},
        },
    },
}

# ============================================================
# 任务系统（新版 - 前3章15个任务）
# ============================================================
ALL_QUESTS = {
    # ══════════════════════════════════════════════
    # 第一章：初入江湖（新手村）
    # ══════════════════════════════════════════════
    "初入江湖": {
        "qid": "chu_ru_jiang_hu",
        "trigger": ["江湖", "入门", "新手", "闯荡", "初来乍到", "醒来"],
        "title": "初入江湖·第一章",
        "type": "传说",
        "stars": 1,
        "desc": "在悦来客栈醒来，失去记忆。向店小二了解江湖常识，领悟'武 = 修心'的初步理念。",
        "reward": "声望+20，修为+30，地图碎片×1",
        "reward_data": {"fame": 20, "exp": 30, "items": [{"name": "江湖地图碎片", "icon": "🧩", "count": 1}]},
        "npc_permission": ["店小二"],
        "prerequisite": None,
        "chapter": 1,
        "chapter_name": "初入江湖",
        "story_context": "玩家在悦来客栈醒来，失去记忆。身上只有一张残破地图。店小二告诉你：江湖不是打打杀杀，而是人情世故。武 = 止戈 = 修心，不是比谁拳头大。",
        "is_key_choice": False,
        "steps": [
            {"id": 1, "desc": "向店小二打听江湖基本规矩（礼数、黑话）", "keywords": ["规矩", "礼数", "江湖规矩", "黑话", "礼节"]},
            {"id": 2, "desc": "了解'武'的真正含义（武 = 止戈 = 修心）", "keywords": ["武", "止戈", "修心", "什么是武", "武侠"]},
            {"id": 3, "desc": "了解一个门派的基本情况（选择门派）", "keywords": ["少林", "武当", "丐帮", "门派", "哪个门派"]},
        ],
    },
    "门派选择": {
        "qid": "men_pai_xuan_ze",
        "trigger": ["门派", "少林", "武当", "丐帮", "选哪个", "拜师"],
        "title": "门派选择·第一章",
        "type": "传说",
        "stars": 1,
        "desc": "了解三大门派（少林/武当/丐帮）的特点，做出选择。每个门派都教'武 = 修心'，只是方法不同。",
        "reward": "声望+10，修为+20",
        "reward_data": {"fame": 10, "exp": 20},
        "npc_permission": ["武林盟主"],
        "prerequisite": "初入江湖",
        "chapter": 1,
        "chapter_name": "初入江湖",
        "story_context": "玩家需要选择门派。武林盟主告诉你：三大门派都教'武 = 修心'，只是方法不同——少林修心（佛宗）、武当修德（道宗）、丐帮修性（市井）。选哪个，都是修心之路。",
        "is_key_choice": False,
        "steps": [
            {"id": 1, "desc": "了解少林（修心 = 易筋经 = 防御+内力恢复）", "keywords": ["少林", "修心", "易筋经", "佛宗"]},
            {"id": 2, "desc": "了解武当（修德 = 太极拳 = 内力+反击）", "keywords": ["武当", "修德", "太极拳", "道宗"]},
            {"id": 3, "desc": "了解丐帮（修性 = 降龙十八掌 = 攻击+暴击）", "keywords": ["丐帮", "修性", "降龙十八掌", "市井"]},
            {"id": 4, "desc": "做出选择（少林/武当/丐帮/无门派）", "keywords": ["选少林", "选武当", "选丐帮", "无门派", "我选"]},
        ],
    },
    "入门修行": {
        "qid": "ru_men_xiu_xing",
        "trigger": ["修行", "练武", "学艺", "拜师", "入门"],
        "title": "入门修行·第一章",
        "type": "传说",
        "stars": 1,
        "desc": "完成门派新手任务，获得入门武学。NPC教你：武学不是用来打架的，而是用来修心的。",
        "reward": "声望+10，修为+30，门派武学入门×1",
        "reward_data": {"fame": 10, "exp": 30, "items": [{"name": "门派武学入门", "icon": "📖", "count": 1}]},
        "npc_permission": ["扫地僧", "武林盟主", "洪七公"],
        "prerequisite": "门派选择",
        "chapter": 1,
        "chapter_name": "初入江湖",
        "story_context": "玩家开始门派修行。对应门派的NPC告诉你：武学不是用来打架的，而是用来修心的。练武的过程，就是修心的过程。",
        "is_key_choice": False,
        "faction_branch": {
            "少林": {
                "steps": [
                    {"id": 1, "desc": "扫地僧教你：练武先修心，易筋经不是武功，是修心之法", "keywords": ["修心", "易筋经", "不是武功", "修心之法"]},
                    {"id": 2, "desc": "学习易筋经入门（防御+内力恢复）", "keywords": ["学习", "易筋经", "入门", "修心"]},
                ],
                "reward_data": {"fame": 10, "exp": 30, "items": [{"name": "易筋经入门", "icon": "📖", "count": 1}]},
            },
            "武当": {
                "steps": [
                    {"id": 1, "desc": "武林盟主教你：太极拳不是打人的，而是'以柔克刚'的修德之法", "keywords": ["修德", "太极拳", "以柔克刚", "不是打人"]},
                    {"id": 2, "desc": "学习太极拳入门（内力+反击）", "keywords": ["学习", "太极拳", "入门", "修德"]},
                ],
                "reward_data": {"fame": 10, "exp": 30, "items": [{"name": "太极拳入门", "icon": "📖", "count": 1}]},
            },
            "丐帮": {
                "steps": [
                    {"id": 1, "desc": "洪七公教你：降龙十八掌不是用来打架的，而是'侠之大者，为国为民'", "keywords": ["修性", "降龙十八掌", "侠之大者", "为国为民"]},
                    {"id": 2, "desc": "学习降龙十八掌入门（攻击+暴击）", "keywords": ["学习", "降龙十八掌", "入门", "修性"]},
                ],
                "reward_data": {"fame": 10, "exp": 30, "items": [{"name": "降龙十八掌入门", "icon": "📖", "count": 1}]},
            },
        },
        "steps": [
            {"id": 1, "desc": "向门派NPC学习入门武学（修心/修德/修性）", "keywords": ["学习", "入门", "修心", "修德", "修性"]},
            {"id": 2, "desc": "领悟'武学不是用来打架的，而是用来修心的'", "keywords": ["领悟", "不是打架", "修心", "明白"]},
        ],
    },
    "江湖第一问": {
        "qid": "jiang_hu_di_yi_wen",
        "trigger": ["战斗", "切磋", "比试", "动手", "打"],
        "title": "江湖第一问·第一章",
        "type": "传说",
        "stars": 1,
        "desc": "教学战斗，但NPC告诉你：真正的武学高手，不需要动手就能解决问题。",
        "reward": "声望+10，修为+20",
        "reward_data": {"fame": 10, "exp": 20},
        "npc_permission": ["扫地僧", "武林盟主", "洪七公"],
        "prerequisite": "入门修行",
        "chapter": 1,
        "chapter_name": "初入江湖",
        "story_context": "玩家第一次接触战斗系统。但NPC告诉你：战斗是最后的手段，不是唯一手段。真正的武学高手，能用智慧解决的，绝不用武力。",
        "is_key_choice": False,
        "steps": [
            {"id": 1, "desc": "NPC教你战斗系统（攻击/智取/撤退），但强调'智取'才是最高境界", "keywords": ["战斗", "智取", "最高境界", "不是打架"]},
            {"id": 2, "desc": "完成一次'智取'战斗（不用武力解决问题）", "keywords": ["智取", "不用武力", "智慧", "解决"]},
        ],
    },
    "酒楼密谈": {
        "qid": "jiu_lou_mi_tan",
        "trigger": ["地图", "残破", "华山", "秘密", "残页"],
        "title": "酒楼密谈·第一章",
        "type": "传说",
        "stars": 1,
        "desc": "店小二悄悄告诉你：你身上有一张残破地图，似乎指向华山。但更重要的是，有人在寻找'九阴真经'，他们以为那是'力量'。",
        "reward": "声望+20，修为+30，地图碎片×1",
        "reward_data": {"fame": 20, "exp": 30, "items": [{"name": "江湖地图碎片", "icon": "🧩", "count": 1}]},
        "npc_permission": ["店小二"],
        "prerequisite": "江湖第一问",
        "chapter": 1,
        "chapter_name": "初入江湖",
        "story_context": "店小二告诉你关于九阴真经的传闻：有人说得经者可得天下武学总纲，但那是错误的。九阴真经其实是'修心指南'，得经者可得'如何修心'的方法。",
        "is_key_choice": False,
        "steps": [
            {"id": 1, "desc": "向店小二打听九阴真经的传闻", "keywords": ["九阴真经", "传闻", "是什么", "修心指南"]},
            {"id": 2, "desc": "了解'九阴'二字的真正含义（九 = 至阴至柔，阴 = 修心）", "keywords": ["九阴", "含义", "至阴至柔", "修心"]},
            {"id": 3, "desc": "决定踏上寻找九阴真经残页的旅程（为了修心，不是为了力量）", "keywords": ["寻找", "修心", "不是为了力量", "旅程"]},
        ],
    },
    # ══════════════════════════════════════════════
    # 第二章：侠客行（行走江湖）
    # ══════════════════════════════════════════════
    "丐帮风云": {
        "qid": "gai_bang_feng_yun",
        "trigger": ["丐帮", "洪七公", "打狗棒", "降龙"],
        "title": "丐帮风云·第二章",
        "type": "传说",
        "stars": 2,
        "desc": "帮丐帮做事，了解江湖势力分布，领悟'修性'的真谛。",
        "reward": "声望+20，修为+40，地图碎片×1",
        "reward_data": {"fame": 20, "exp": 40, "items": [{"name": "江湖地图碎片", "icon": "🧩", "count": 1}]},
        "npc_permission": ["洪七公"],
        "prerequisite": "酒楼密谈",
        "chapter": 2,
        "chapter_name": "侠客行",
        "story_context": "洪七公告诉你：丐帮的'修性'，不是让你去讨饭，而是让你在市井中修心。真正的武者，能和光同尘，能在任何环境中保持本心。",
        "is_key_choice": False,
        "steps": [
            {"id": 1, "desc": "帮洪七公做事（送信/乞讨/打探消息）", "keywords": ["做事", "送信", "乞讨", "打探"]},
            {"id": 2, "desc": "领悟'修性'的真谛（在市井中修心）", "keywords": ["修性", "市井", "修心", "真谛"]},
        ],
    },
    "剑宗遗秘": {
        "qid": "jian_zong_yi_mi",
        "trigger": ["独孤九剑", "剑宗", "思过崖", "风清扬"],
        "title": "剑宗遗秘·第二章",
        "type": "传说",
        "stars": 2,
        "desc": "前往华山思过崖，风清扬传授独孤九剑（剑宗路线）。但他说：剑法的最高境界，是'不战而屈人之兵'。",
        "reward": "声望+20，修为+40，地图碎片×1",
        "reward_data": {"fame": 20, "exp": 40, "items": [{"name": "江湖地图碎片", "icon": "🧩", "count": 1}]},
        "npc_permission": ["风清扬"],
        "prerequisite": "酒楼密谈",
        "chapter": 2,
        "chapter_name": "侠客行",
        "story_context": "风清扬告诉你：独孤九剑的精髓，不是'打败对手'，而是'后发先至，以柔克刚'——这才是'止戈'的真谛。剑法，是修心之法，不是杀戮之法。",
        "is_key_choice": False,
        "steps": [
            {"id": 1, "desc": "前往华山思过崖，找到风清扬", "keywords": ["思过崖", "风清扬", "找到", "前往"]},
            {"id": 2, "desc": "风清扬传授独孤九剑，但强调'不战而屈人之兵'", "keywords": ["独孤九剑", "不战而屈人之兵", "止戈", "修心"]},
        ],
    },
    "少林问禅": {
        "qid": "shao_lin_wen_chan",
        "trigger": ["易筋经", "扫地僧", "少林", "禅宗"],
        "title": "少林问禅·第二章",
        "type": "传说",
        "stars": 2,
        "desc": "前往少林寺，扫地僧传授易筋经（佛宗路线）。但他说：易筋经不是武功，而是修心之法。",
        "reward": "声望+20，修为+40，地图碎片×1",
        "reward_data": {"fame": 20, "exp": 40, "items": [{"name": "江湖地图碎片", "icon": "🧩", "count": 1}]},
        "npc_permission": ["扫地僧"],
        "prerequisite": "酒楼密谈",
        "chapter": 2,
        "chapter_name": "侠客行",
        "story_context": "扫地僧告诉你：易筋经不是武功秘籍，而是修心指南。练易筋经，不是为了让身体更强壮，而是为了让心更平静。真正的力量，来自于内心的平静。",
        "is_key_choice": False,
        "steps": [
            {"id": 1, "desc": "前往少林寺，找到扫地僧", "keywords": ["少林寺", "扫地僧", "找到", "前往"]},
            {"id": 2, "desc": "扫地僧传授易筋经入门，强调'练武先修心'", "keywords": ["易筋经", "修心", "练武先修心", "不是武功"]},
        ],
    },
    "武当论道": {
        "qid": "wu_dang_lun_dao",
        "trigger": ["太极拳", "武当", "张三丰", "内家"],
        "title": "武当论道·第二章",
        "type": "传说",
        "stars": 2,
        "desc": "前往武当山，学习太极拳（道宗路线）。但武林盟主说：太极拳不是打人的，而是'以柔克刚'的修德之法。",
        "reward": "声望+20，修为+40，地图碎片×1",
        "reward_data": {"fame": 20, "exp": 40, "items": [{"name": "江湖地图碎片", "icon": "🧩", "count": 1}]},
        "npc_permission": ["武林盟主"],
        "prerequisite": "酒楼密谈",
        "chapter": 2,
        "chapter_name": "侠客行",
        "story_context": "武林盟主告诉你：太极拳的精髓，不是'天下无敌'，而是'以柔克刚，四两拨千斤'。真正的武者，不需要证明自己。太极拳，是修德之法，不是杀戮之法。",
        "is_key_choice": False,
        "steps": [
            {"id": 1, "desc": "前往武当山，向武林盟主学习太极拳", "keywords": ["武当山", "太极拳", "学习", "前往"]},
            {"id": 2, "desc": "武林盟主教你太极拳入门，强调'以柔克刚'的修德之法", "keywords": ["太极拳", "以柔克刚", "修德", "不是打人"]},
        ],
    },
    "地图拼合": {
        "qid": "di_tu_pin_he",
        "trigger": ["拼图", "集齐", "黑木崖", "日月神教"],
        "title": "地图拼合·第二章",
        "type": "传说",
        "stars": 2,
        "desc": "集齐3块地图碎片，拼出完整地图，发现指向【黑木崖】。但店小二提醒你：黑木崖上的人，误解了'武'。",
        "reward": "声望+30，修为+50，地图碎片×2",
        "reward_data": {"fame": 30, "exp": 50, "items": [{"name": "江湖地图碎片", "icon": "🧩", "count": 2}]},
        "npc_permission": ["店小二"],
        "prerequisite": "丐帮风云",  # 任意一个第二章任务完成即可
        "chapter": 2,
        "chapter_name": "侠客行",
        "story_context": "你集齐了3块地图碎片，拼出了完整地图。地图指向【黑木崖】——日月神教的总舵。店小二提醒你：黑木崖上的任我行，练了一辈子武，但越来越痛苦。因为他误解了'武'。",
        "is_key_choice": False,
        "steps": [
            {"id": 1, "desc": "集齐3块地图碎片", "keywords": ["集齐", "碎片", "3块", "拼图"]},
            {"id": 2, "desc": "拼出完整地图，发现指向【黑木崖】", "keywords": ["拼合", "完整", "黑木崖", "指向"]},
            {"id": 3, "desc": "了解任我行的故事（他误解了'武'）", "keywords": ["任我行", "误解", "武", "痛苦"]},
        ],
    },
    # ══════════════════════════════════════════════
    # 第三章：误解显现（门派冲突）
    # ══════════════════════════════════════════════
    "神秘人现身": {
        "qid": "shen_mi_ren_xian_shen",
        "trigger": ["神秘人", "风无痕", "观察", "秘密"],
        "title": "神秘人现身·第三章",
        "type": "传说",
        "stars": 3,
        "desc": "风无痕首次正式登场，告诉你：'各门派都误解了九阴真经，他们以为它是力量'。",
        "reward": "声望+30，修为+50，九阴残页×1",
        "reward_data": {"fame": 30, "exp": 50, "items": [{"name": "九阴残页", "icon": "📜", "count": 1}]},
        "npc_permission": ["神秘大侠"],
        "prerequisite": "地图拼合",
        "chapter": 3,
        "chapter_name": "误解显现",
        "story_context": "风无痕告诉你：九阴真经不是'武功秘籍'，而是'修心指南'。但各门派都误解了它，以为得经者可得天下武学总纲。你的任务是：帮助江湖明白'武 = 止戈 = 修心'。",
        "is_key_choice": False,
        "steps": [
            {"id": 1, "desc": "风无痕首次正式登场，告诉你九阴真经的真相", "keywords": ["风无痕", "真相", "修心指南", "不是武功秘籍"]},
            {"id": 2, "desc": "了解你的任务：帮助江湖明白'武 = 止戈 = 修心'", "keywords": ["任务", "帮助", "江湖", "止戈", "修心"]},
        ],
    },
    "白驼山庄的执念": {
        "qid": "bai_tuo_shan_zhuang",
        "trigger": ["欧阳克", "白驼山", "执念", "天下无敌"],
        "title": "白驼山庄的执念·第三章",
        "type": "传说",
        "stars": 3,
        "desc": "发现欧阳克在收集九阴真经残页，他以为得到它就能天下无敌。你需要让他明白：'武 ≠ 力量'。",
        "reward": "声望+30，修为+50",
        "reward_data": {"fame": 30, "exp": 50},
        "npc_permission": ["欧阳克"],
        "prerequisite": "神秘人现身",
        "chapter": 3,
        "chapter_name": "误解显现",
        "story_context": "欧阳克误解了'武'——他以为'武 = 力量 = 天下无敌'。你需要让他明白：武 = 止戈 = 修心。力量越大，责任越大，越不能轻易使用。",
        "is_key_choice": False,
        "steps": [
            {"id": 1, "desc": "发现欧阳克在收集九阴真经残页", "keywords": ["欧阳克", "收集", "残页", "发现"]},
            {"id": 2, "desc": "试图让欧阳克明白'武 ≠ 力量'（通过对话或战斗）", "keywords": ["武 ≠ 力量", "止戈", "修心", "明白"]},
        ],
    },
    "唐门暗器": {
        "qid": "tang_men_an_qi",
        "trigger": ["唐门", "暗器", "唐巧", "误解"],
        "title": "唐门暗器·第三章",
        "type": "传说",
        "stars": 3,
        "desc": "唐门被欧阳克收买，玩家需要让他们明白'武 ≠ 力量'。",
        "reward": "声望+30，修为+50",
        "reward_data": {"fame": 30, "exp": 50},
        "npc_permission": ["唐巧"],
        "prerequisite": "白驼山庄的执念",
        "chapter": 3,
        "chapter_name": "误解显现",
        "story_context": "唐门也误解了'武'——他们以为'武 = 暗器 = 可以暗杀任何人'。你需要让他们明白：真正的武者，不会滥杀无辜。武德之一，就是'仁'。",
        "is_key_choice": False,
        "steps": [
            {"id": 1, "desc": "了解唐门被欧阳克收买的情况", "keywords": ["唐门", "收买", "欧阳克", "情况"]},
            {"id": 2, "desc": "让唐门明白'武 ≠ 力量'，武德之一是'仁'", "keywords": ["武德", "仁", "不是滥杀", "明白"]},
        ],
    },
    "门派大会": {
        "qid": "men_pai_da_hui",
        "trigger": ["大会", "争论", "归属", "武功秘籍"],
        "title": "门派大会·第三章",
        "type": "传说",
        "stars": 3,
        "desc": "各门派汇聚武林盟主府，争论九阴真经残页的归属问题。他们都以为经书是'武功秘籍'。",
        "reward": "声望+30，修为+50",
        "reward_data": {"fame": 30, "exp": 50},
        "npc_permission": ["武林盟主"],
        "prerequisite": "唐门暗器",
        "chapter": 3,
        "chapter_name": "误解显现",
        "story_context": "各门派都误解了九阴真经——他们以为它是'武功秘籍'，得经者可得天下武学总纲。你需要让他们明白：九阴真经是'修心指南'，不是'力量之源'。",
        "is_key_choice": False,
        "steps": [
            {"id": 1, "desc": "参加门派大会，听各门派争论九阴真经的归属", "keywords": ["大会", "争论", "归属", "参加"]},
            {"id": 2, "desc": "试图让各门派明白'九阴真经是修心指南，不是武功秘籍'", "keywords": ["修心指南", "不是武功秘籍", "明白", "说服"]},
        ],
    },
    "第一次抉择": {
        "qid": "di_yi_ci_jue_ze",
        "trigger": ["选择", "感化", "传道", "传承"],
        "title": "第一次抉择·第三章",
        "type": "传说",
        "stars": 3,
        "desc": "玩家需要选择：如何用九阴真经帮助江湖？（A.感化各门派 B.自创武学传道 C.寻找值得的人传承）",
        "reward": "声望+50，修为+80，九阴残页×1",
        "reward_data": {"fame": 50, "exp": 80, "items": [{"name": "九阴残页", "icon": "📜", "count": 1}]},
        "npc_permission": ["神秘大侠"],
        "prerequisite": "门派大会",
        "chapter": 3,
        "chapter_name": "误解显现",
        "story_context": "风无痕让你做出选择：如何用九阴真经帮助江湖？A.感化各门派（让他们明白'武 = 止戈 = 修心'）；B.自创武学传道（开宗立派，传授修心理念）；C.寻找值得的人传承（把经书交给有缘人）。",
        "is_key_choice": True,
        "choice_impact": ["gan_hua", "chuan_dao", "chuan_cheng"],  # 感化/传道/传承
        "steps": [
            {"id": 1, "desc": "听取风无痕的建议，了解三种选择的含义", "keywords": ["选择", "感化", "传道", "传承", "含义"]},
            {"id": 2, "desc": "做出选择（A.感化各门派 / B.自创武学传道 / C.寻找值得的人传承）", "keywords": ["选A", "选B", "选C", "我选", "决定"]},
        ],
    },
}
'''
    
    # 找到旧 ALL_QUESTS 的位置并替换
    # 先找到 ALL_QUESTS = { 的位置
    start_idx = content.find('ALL_QUESTS = {')
    if start_idx == -1:
        print("错误：找不到 ALL_QUESTS = {")
        exit(1)
    
    # 找到对应的 }（字典结束）
    # 简单方法：找到下一个 # ========= 或者文件末尾
    # 实际上，旧的 ALL_QUESTS 在文件末尾，所以我们可以找到它后面的内容
    
    # 让我用更简单的方法：直接找到 ALL_QUESTS = { 和最后一个 }
    # 计算括号匹配
    brace_count = 0
    in_all_quests = False
    end_idx = len(content)
    
    for i in range(start_idx, len(content)):
        if content[i] == '{':
            brace_count += 1
            in_all_quests = True
        elif content[i] == '}':
            brace_count -= 1
            if in_all_quests and brace_count == 0:
                end_idx = i + 1
                break
    
    print(f"找到 ALL_QUESTS：从 {start_idx} 到 {end_idx}")
    
    # 替换
    new_content = content[:start_idx] + npc_gift_new
    
    # 写回文件
    with open(r'C:\Users\aaa\PycharmProjects\day25\江湖百晓生_vue\prompts.py', 'w', encoding='utf-8') as f:
        f.write(new_content)
    
    print("成功修改 prompts.py！")
    print(f"文件长度：{len(new_content)} 字符")
