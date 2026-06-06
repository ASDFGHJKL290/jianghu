# -*- coding: utf-8 -*-
"""
main.py — 江湖百晓生 v2.0 FastAPI 入口 & 路由
业务逻辑已拆分至 game.py，本文件只负责 HTTP 层
"""

import os, uuid, time, asyncio, re
# 关闭 LangSmith tracing（国内网络不通，会刷 ReadTimeout 错误）
os.environ["LANGCHAIN_TRACING_V2"] = "false"
from contextlib import asynccontextmanager
from fastapi import FastAPI, File, UploadFile, Form, HTTPException, Query
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware

import game as g

# ── JianghuChat（延迟导入，避免循环依赖） ────────
from chat import JianghuChat
from npc_data import NPC_PROFILES
from quest_data import ALL_QUESTS

# ── 后台世界推进tick ────────────────────────────
_world_tick_task = None

async def _world_tick_loop():
    """每30秒推进一次世界状态"""
    while True:
        await asyncio.sleep(30)
        try:
            if g.chat and g.chat.event_manager:
                em = g.chat.event_manager
                em.tick()
                if em.diag.last_tick_msg:
                    print(em.diag.last_tick_msg, flush=True)
        except Exception as e:
            print(f"[WorldTick] {e}")

@asynccontextmanager
async def lifespan(app):
    global _world_tick_task
    import game as g
    # 加载持久化状态（玩家数据、聊天记录、情感等）
    try:
        g.load_all_state()
    except Exception:
        pass
    # 启动时清理旧邮箱消息（保留最近20条，防止旧debug数据堆积）
    try:
        msgs = g._load_mailbox()
        for uid in msgs:
            if len(msgs[uid]) > 20:
                msgs[uid] = msgs[uid][-20:]
        g._save_mailbox(msgs)
    except Exception:
        pass
    _world_tick_task = asyncio.create_task(_world_tick_loop())
    yield
    _world_tick_task.cancel()
    # 清理 Katago 孤儿进程（避免霸占CPU）
    import subprocess
    subprocess.run(["taskkill", "/F", "/IM", "katago.exe"],
                   capture_output=True, timeout=5)

# ── 启动 FastAPI ────────────────────────────────
app = FastAPI(title="江湖百晓生 v2.0", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["*"],
                   allow_credentials=True, allow_methods=["*"], allow_headers=["*"])

# 注入 JianghuChat 实例（初始化失败不阻塞服务启动）
_init_error = None
try:
    g.chat = JianghuChat()
except Exception as e:
    g.chat = None
    _init_error = f"JianghuChat初始化失败: {e}"
    print(f"[启动] 致命错误: {_init_error}")

if g.chat is not None:
    g.chat.event_manager = None  # 由后续初始化填入

    # 初始化事件引擎
    from event_engine import EventManager
    g.chat.event_manager = EventManager(g.chat)
    # 自动选中一个节点组
    try:
        g.chat.event_manager.select_group()
        print(f"[启动] 选中节点组: {g.chat.event_manager._current_group_id}")
    except Exception as e:
        print(f"[启动] 节点组选择跳过（{e}）")

# 健康检查路由
@app.get("/api/health")
async def health():
    if g.chat is None:
        return {"status": "error", "detail": _init_error}
    return {"status": "ok", "game_day": g.game_day}

# ── 静态文件 ────────────────────────────────────
app.mount("/static", StaticFiles(directory=os.path.join(g.BASE_DIR, "static")), name="static")

# ── 根路径 ──────────────────────────────────────
@app.get("/")
async def root_page():
    return FileResponse(os.path.join(g.BASE_DIR, "static", "index.html"))


# ════════════════════════════════════════════════
# 聊天 API
# ════════════════════════════════════════════════
@app.post("/api/chat")
async def api_chat(req: g.ChatReq):
    if g.chat is None:
        return JSONResponse({"reply": "系统正在初始化，请稍后刷新页面重试。", "emotion_state": {}, "actions": []})
    npc = req.npc_name if req.npc_name in NPC_PROFILES else "店小二"
    uid = req.user_id or "default"

    g.update_activity(npc, uid)
    h = g.get_hist(npc, uid)
    resp = g.chat.chat(req.message, h, npc, uid)
    g.set_hist(npc, uid, resp.pop("_history", []))

    quest_reward_info = []
    breakthrough_info = None
    old_realm = g.get_realm_info(g.exp)

    for qc in resp.get("quest_completed", []):
        rd = qc.get("reward_data", {})
        if rd.get("exp"):  g.exp += rd["exp"]
        if rd.get("silver"): g.silver += rd.get("silver", 0)
        if rd.get("items"):
            for it in rd["items"]:
                found = next((x for x in g.player_items if x["name"] == it["name"]), None)
                if found:
                    found["count"] = found.get("count", 1) + it.get("count", 1)
                else:
                    g.player_items.append(dict(it))
        # 亲密度奖励（完成对应NPC的任务提升好感）
        if rd.get("intimacy"):
            from_npc = qc.get("from_npc", npc)
            g.chat.memory.update_relation(uid, from_npc, rd["intimacy"])
        quest_reward_info.append({
            "title": qc.get("title", ""),
            "reward": qc.get("reward", ""),
            "next_hint": qc.get("next_hint", ""),
        })

    new_realm = g.get_realm_info(g.exp)
    if new_realm["level"] > old_realm["level"]:
        breakthrough_info = {
            "old_level": old_realm["level"], "old_name": old_realm["name"],
            "new_level": new_realm["level"], "new_name": new_realm["name"],
            "new_title": new_realm["title"],
        }

    # 初入江湖任务完成 → 推进到 Step 4 教学战斗
    tutorial_advanced = False
    if g.tutorial_step in [2, 3]:
        for qc in resp.get("quest_completed", []):
            if "初入江湖" in qc.get("title", ""):
                g.tutorial_step = 4; tutorial_advanced = True; break
    
    # 只有发生"有意义的事"才过天（任务推进/完成/战斗）
    had_progress = (resp.get("quest_step_completed") and len(resp["quest_step_completed"]) > 0
                    or resp.get("quest_completed") and len(resp["quest_completed"]) > 0
                    or resp.get("combat_result"))
    if had_progress:
        g.game_day += 1
    
    # 处理章节推进
    chapter_advancement = resp.get("chapter_advancement", {"advanced": False})
    
    # 处理礼物信息
    gift_info = resp.get("gift")
    if gift_info and gift_info.get("item"):
        item_name = gift_info["item"]
        # 清理 LLM 可能附加的 emoji: "花瓣(🌸)" → "花瓣"
        item_name_clean = re.sub(r'[^\w\u4e00-\u9fff]', '', item_name.split('(')[0].split('（')[0].strip())
        from npc_data import NPC_GIFT_CONFIG
        # 查找礼物配置（先精确匹配，再模糊匹配）
        gift_config = None
        for npc_name, cfg in NPC_GIFT_CONFIG.items():
            for gift in cfg.get("items", []):
                if gift.get("name") == item_name or gift.get("name") == item_name_clean:
                    gift_config = gift
                    break
            if gift_config:
                break
        # 也检查 milestone 礼物
        if not gift_config:
            for npc_name, cfg in NPC_GIFT_CONFIG.items():
                for level, item in cfg.get("milestone", {}).items():
                    if item.get("name") == item_name or item.get("name") == item_name_clean:
                        gift_config = item
                        gift_config["count"] = item.get("count", 1)
                        break
                if gift_config:
                    break
        
        if gift_config:
            # 查 ITEM_EFFECTS 补 type/value/desc 字段
            eff = g.ITEM_EFFECTS.get(gift_config["name"], {})

            # 添加礼物到玩家物品列表
            found = next((x for x in g.player_items if x["name"] == gift_config["name"]), None)
            if found:
                found["count"] = found.get("count", 1) + gift_config.get("count", 1)
            else:
                g.player_items.append({
                    "name": gift_config["name"],
                    "icon": gift_config.get("icon", "🎁"),
                    "count": gift_config.get("count", 1),
                    "type": eff.get("type", ""),
                    "value": eff.get("value", 0),
                    "desc": eff.get("desc", ""),
                    "effect": eff.get("desc", ""),
                    "target": eff.get("target", ""),
                })
            
            # 富化 gift_info 传给前端弹窗
            gift_info["icon"] = gift_config.get("icon", "🎁")
            gift_info["count"] = gift_config.get("count", 1)
            gift_info["note"] = eff.get("desc", gift_config.get("desc", ""))
        else:
            # 兜底：配置中没找到礼物名称，直接创建基础道具
            g.player_items.append({
                "name": item_name,
                "icon": "🎁",
                "count": 1,
                "type": "",
                "value": 0,
                "desc": "",
                "effect": "",
                "target": "",
            })
            gift_info["icon"] = "🎁"
            gift_info["count"] = 1
    
    # 新手引导完成指引
    tutorial_complete_guide = None
    if g.tutorial_step >= 7:
        tutorial_complete_guide = g.TUTORIAL_COMPLETE_GUIDE

    # 邮箱消息生成：其他NPC根据动机主动给玩家发消息
    # 每次聊天最多推3条，防止轰炸
    unlocked_locs = set(g.get_unlocked_locations())
    mail_count = 0
    for other_npc in NPC_PROFILES:
        if other_npc == npc:
            continue  # 跳过当前正在对话的NPC
        if mail_count >= 1:
            break  # 每次聊天最多1条飞鸽
        # 检查地图是否解锁，未解锁的NPC不发消息
        npc_loc = NPC_PROFILES[other_npc].get("location", "")
        if npc_loc and npc_loc not in unlocked_locs:
            continue
        if g.chat.motivation_manager.should_message(other_npc):
            try:
                mot = g.chat.motivation_manager.get(other_npc)
                content = g.chat.generate_mail_message(other_npc, mot)
                g.add_mail_message(uid, other_npc, content, mot.get("mood", ""))
                mail_count += 1
            except Exception:
                pass  # 消息生成失败不影响主流程

    g.save_all_state()
    return {
        "reply": resp["reply"],
        "new_quests": resp["new_quests"],
        "quest_reward": quest_reward_info,
        "quest_step_completed": resp.get("quest_step_completed", []),
        "emotion_state": resp["emotion_state"],
        "actions": resp["actions"],
        "game_day": g.game_day,
        "items": g.player_items,
        "silver": g.silver,
        "exp": g.exp,
        "realm": new_realm,
        "breakthrough": breakthrough_info,
        "voice_params": {"speed": 1.0, "pitch": "0%", "volume": 1.0, "style": "default"},
        "audio_url": None,
        "new_relation": resp.get("new_relation"),
        "tutorial_step": g.tutorial_step,
        "tutorial_advanced": tutorial_advanced,
        "chapter_advancement": chapter_advancement,
        "outcome_info": resp.get("outcome_info"),
        "gift": gift_info,
        "work_reward": resp.get("work_reward", 0),
        "tutorial_complete_guide": tutorial_complete_guide,
        "go_problem": resp.get("go_problem", {}),
    }

@app.post("/api/chat/text")
async def api_chat_text(req: g.ChatReq):
    npc = req.npc_name if req.npc_name in NPC_PROFILES else "店小二"
    uid = req.user_id or "default"
    g.update_activity(npc, uid)
    h = g.get_hist(npc, uid)
    resp = g.chat.chat(req.message, h, npc, uid)
    g.set_hist(npc, uid, resp.pop("_history", []))
    # 只有任务推进/完成才过天
    if (resp.get("quest_completed") and len(resp["quest_completed"]) > 0
            or resp.get("quest_step_completed") and len(resp["quest_step_completed"]) > 0):
        g.game_day += 1
    g.save_all_state()
    return {
        "reply": resp["reply"], "new_quests": resp["new_quests"],
        "game_day": g.game_day, "exp": g.exp,
        "realm": g.get_realm_info(g.exp),
    }


# ════════════════════════════════════════════════
# 任务 API
# ════════════════════════════════════════════════
@app.get("/api/quests")
async def get_quests(user_id: str = Query("default")):
    return {"quests": g.chat._user_quests(user_id)}

@app.get("/api/quest/progress")
async def get_quest_progress(user_id: str = Query("default")):
    result = []
    for quest in g.chat._user_quests(user_id):
        qid = quest.get("qid")
        progress = g.chat.quest_progress.get(user_id, {}).get(qid) or {"current_step": 1, "completed_steps": []}
        # 为每个步骤注入关键词提示
        enriched_steps = []
        for step in quest.get("steps", []):
            step_copy = dict(step)
            # 取前2-3个关键词作为提示
            kws = step_copy.get("keywords", [])
            if kws:
                hint_kw = kws[:3]
                step_copy["hint"] = f"💡 试试说：{'、'.join(hint_kw)}"
            enriched_steps.append(step_copy)
        enriched_quest = {**quest, "steps": enriched_steps, "progress": progress}
        result.append(enriched_quest)
    return {"quests": result}

@app.post("/api/clear")
async def clear_hist(req: g.ClearReq):
    to_del = [k for k in g.histories if k.startswith(req.npc_name + "|")]
    for k in to_del: del g.histories[k]
    return {"ok": True}

@app.post("/api/quest/abandon")
async def abandon(req: g.AbandonReq):
    uid = req.user_id or "default"
    g.chat.active_quests[uid] = [q for q in g.chat.active_quests.get(uid, [])
                                   if q.get("qid") != req.qid]
    if req.qid in g.chat.quest_completion.get(uid, {}):
        del g.chat.quest_completion[uid][req.qid]
    g.save_all_state()
    return {"status": "ok"}

@app.get("/api/debug/quests")
async def debug_quests(user_id: str = Query("default")):
    return {"active": g.chat._user_quests(user_id),
            "completed": list(g.chat.quest_completion.keys())}


# ════════════════════════════════════════════════
# 玩家状态 API
# ════════════════════════════════════════════════
@app.get("/api/weather")
async def weather():
    return g.chat.weather

@app.get("/api/game_day")
async def get_game_day():
    return {"game_day": g.game_day}

@app.get("/api/player")
async def get_player():
    realm = g.get_realm_info(g.exp)
    return {
        "game_day": g.game_day, "items": g.player_items, "silver": g.silver,
        "exp": g.exp, "realm": realm,
        "active_quests": g.chat.active_quests,
        "quest_completion": g.chat.quest_completion,
        "quest_progress": g.chat.quest_progress,
    }

@app.post("/api/player")
async def save_player():
    g.save_all_state()
    return {"status": "ok", "game_day": g.game_day, "exp": g.exp,
            "realm": g.get_realm_info(g.exp)}


# ════════════════════════════════════════════════
# NPC & 关系 API
# ════════════════════════════════════════════════
@app.get("/api/npcs")
async def npcs():
    return [{"name": k, "avatar": v["avatar"],
             "location": v["location"], "greeting": v["greeting"]}
            for k, v in NPC_PROFILES.items()]

@app.get("/api/relation")
async def get_relation(user_id: str = "default"):
    return g.chat.memory.get_all_relations(user_id)

@app.get("/api/emotion/{npc_name}")
async def get_emotion(npc_name: str):
    state = g.chat.emotion_engine._history.get(npc_name, [])
    return state[-1] if state else g.chat.emotion_engine._default()

@app.get("/api/memory/{npc_name}")
async def get_memory(npc_name: str):
    return g.chat.memory.get_longterm(npc_name)


@app.get("/api/npc/info/{npc_name}")
async def get_npc_info(npc_name: str, user_id: str = "default"):
    """聚合 NPC 认知模拟数据：情感+记忆+动机+知识图谱关系"""
    # 情感状态
    emotion_history = g.chat.emotion_engine._history.get(npc_name, [])
    emotion = emotion_history[-1] if emotion_history else g.chat.emotion_engine._default()

    # 长期记忆（按权重分层）
    ltm = g.chat.memory.get_longterm(npc_name)
    memories_by_layer = {"rare": [], "uncommon": [], "low": []}
    for evt in ltm.get("key_events", []):
        w = evt.get("weight", 0.5)
        fixed = evt.get("fixed", False)
        if w >= 0.6 or fixed:
            memories_by_layer["rare"].append({"event": evt["event"], "weight": w, "fixed": fixed})
        elif w >= 0.3:
            memories_by_layer["uncommon"].append({"event": evt["event"], "weight": w})
        elif w > 0.1:
            memories_by_layer["low"].append({"event": evt["event"], "weight": w})

    # 动机
    motivation = g.chat.motivation_manager.get(npc_name)

    # 知识图谱关系
    em = g.chat.event_manager
    kg_neighbors = []
    if em and hasattr(em, 'kg'):
        for neighbor in em.kg.G.neighbors(npc_name):
            edge = em.kg.G.edges[npc_name, neighbor]
            kg_neighbors.append({"name": neighbor, "relation": edge.get("relation", "关联"),
                                "type": em.kg.G.nodes[neighbor].get("type", "npc")})

    # 活跃事件
    active_context = em.get_events_for_context(npc_name) if em else ""
    chain_context = em.get_chain_context_for_npc(npc_name) if em else ""

    return {
        "npc_name": npc_name,
        "emotion": emotion,                     # valence/arousal/dominance/trend/...
        "motivation": motivation,               # drive/mood/goal
        "memory": {                             # 三层记忆
            "total": len(ltm.get("key_events", [])),
            "rare_count": len(memories_by_layer["rare"]),
            "uncommon_count": len(memories_by_layer["uncommon"]),
            "low_count": len(memories_by_layer["low"]),
            "samples": {
                "rare": [m["event"][:40] for m in memories_by_layer["rare"][:3]],
                "uncommon": [m["event"][:40] for m in memories_by_layer["uncommon"][:3]],
            },
        },
        "kg": {                                 # 知识图谱
            "neighbor_count": len(kg_neighbors),
            "neighbors": [n["name"] for n in kg_neighbors],
            "neighbors_detail": kg_neighbors,
        },
        "active_context": {
            "has_events": bool(active_context),
            "has_chain": bool(chain_context),
        },
    }


# ════════════════════════════════════════════════
# 战斗 API
# ════════════════════════════════════════════════
@app.post("/api/combat/start")
async def combat_start(req: g.CombatReq):
    return g.combat_start(req.npc_name)

@app.post("/api/combat/action")
async def combat_action(req: g.CombatReq):
    try:
        # game.py 算伤害数值
        result = g.combat_action(req.action, req.npc_name)
        # status 动作已在 game.py 直接返回 reply，跳过 LLM
        if req.action == "status":
            return result
        cr = result["combat_result"]
        # 累积战斗叙事历史 + 背景（保持每轮LLM叙事前后一致）
        combat_hist = ""
        bg = g.combat_narrative.get(f"{req.npc_name}_bg", "")
        narratives = g.combat_narrative.get(req.npc_name, [])
        if narratives:
            combat_hist = "\n".join(narratives[-4:])  # 最近4轮
        # LLM 生成武侠叙事
        reply = g.chat.combat_chat(
            npc_name=req.npc_name,
            action=req.action,
            player_hp=result["player_hp"],
            enemy_hp=result["enemy_hp"],
            player_dmg=cr.get("player_dmg", 0),
            enemy_dmg=cr.get("enemy_dmg", 0),
            status=cr["status"],
            combat_history=combat_hist,
            background=bg if not narratives else "",  # 背景只在第一轮传
        )
        # 累积本轮的叙事
        if reply:
            g.combat_narrative.setdefault(req.npc_name, []).append(reply)
        result["reply"] = reply
        # 战斗结束：过一天 + 写记忆
        if cr["status"] in ("victory", "defeat", "flee", "escape", "draw"):
            g.game_day += 1
            # 写入战斗记忆（简洁概括，后续对话中NPC会提到）
            outcome_map = {"victory": "击败", "defeat": "败给", "flee": "逃脱", "escape": "逃离", "draw": "与...战平"}
            outcome = outcome_map.get(cr["status"], "与")
            summary = f"曾与玩家{outcome}——一场比武"
            g.chat.memory.update_longterm(req.npc_name, summary, layer="uncommon")
            # 清理叙事累积
            g.combat_narrative.pop(req.npc_name, None)
            g.combat_narrative.pop(f"{req.npc_name}_bg", None)
        # 战斗胜利 / 突破时追加额外提示
        if cr["status"] == "victory" and cr.get("exp_gained"):
            result["reply"] += f"\n\n🎉 战斗胜利！获得 {cr['exp_gained']} 点修为！"
            bt = result.get("breakthrough")
            if bt:
                result["reply"] += f"\n🔥 境界突破：{bt['old_name']} → {bt['new_name']}！"
        return result
    except ValueError as e:
        return JSONResponse(
            {"ok": False, "error": str(e), "reset_combat": True},
            status_code=200,
        )


# ════════════════════════════════════════════════
# 道具 API
# ════════════════════════════════════════════════
@app.post("/api/item/use")
async def use_item(item_name: str = Form(...), target_npc: str = Form(default="")):
    found = next((it for it in g.player_items if it["name"] == item_name), None)
    if not found:
        return JSONResponse({"ok": False, "error": "背包中没有此道具"}, status_code=400)
    if found["count"] <= 0:
        return JSONResponse({"ok": False, "error": "道具已用完"}, status_code=400)
    effect = g.ITEM_EFFECTS.get(item_name)
    if not effect:
        return JSONResponse({"ok": False, "error": "此道具无法使用"}, status_code=400)

    result_msg = ""; applied = {}
    if effect["type"] == "hp":
        applied["hp"] = effect["value"]
        for _st in g.combat_state.values():
            if _st.get("status") == "ongoing":
                _st["player_hp"] = min(_st["player_hp"] + effect["value"], 100)
        result_msg = f"你服下{found['name']}，恢复{effect['value']}点气血"
    elif effect["type"] == "favor":
        target = target_npc if target_npc else effect.get("target", "店小二")
        new_favor = g.chat.memory.get_relation("default", target) + effect["value"]
        g.chat.memory.update_relation("default", target, effect["value"])
        applied["favor"] = {"npc": target, "value": new_favor}
        result_msg = f"你将{found['name']}递给{target}，好感度+{effect['value']}"
    elif effect["type"] == "equip":
        applied["equip"] = item_name
        result_msg = f"你装备了{found['name']}，战斗伤害+{effect['value']}%"
    elif effect["type"] == "silver":
        g.silver += effect["value"]; applied["silver"] = effect["value"]
        result_msg = f"你取出碎银{effect['value']}两，现有{g.silver}两"

    found["count"] -= 1
    if found["count"] <= 0: g.player_items.remove(found)
    g.save_all_state()
    return {"ok": True, "message": result_msg, "applied": applied, "items": g.player_items}

@app.get("/api/item/effects")
async def get_item_effects():
    return {"effects": g.ITEM_EFFECTS}


# ════════════════════════════════════════════════
# 商店 API
# ════════════════════════════════════════════════
@app.get("/api/shop/items")
async def get_shop_items():
    return {"items": g.SHOP_ITEMS, "silver": g.silver}

@app.post("/api/shop/buy")
async def shop_buy(req: g.ShopBuyReq):
    if req.item_name not in g.SHOP_ITEMS:
        return JSONResponse({"ok": False, "error": "商店没有此商品"}, status_code=400)
    item_info = g.SHOP_ITEMS[req.item_name]
    total = item_info["price"] * max(req.count, 1)
    if g.silver < total:
        return JSONResponse({"ok": False, "error": f"银子不足，需要{total}两"}, status_code=400)
    g.silver -= total
    found = next((it for it in g.player_items if it["name"] == req.item_name), None)
    if found: found["count"] = found.get("count", 1) + max(req.count, 1)
    else: g.player_items.append({"name": req.item_name, "icon": item_info["icon"], "count": max(req.count, 1)})
    g.save_all_state()
    return {
        "ok": True, "message": f"购买成功！获得 {req.item_name} ×{max(req.count, 1)}",
        "silver": g.silver, "items": g.player_items,
        "exp": g.exp, "realm": g.get_realm_info(g.exp),
    }


# ════════════════════════════════════════════════
# 地图 API
# ════════════════════════════════════════════════
@app.get("/api/map/status")
async def map_status():
    return {
        "fragment_count": g.get_map_fragment_count(),
        "unlocked": g.get_unlocked_locations(),
    }

@app.get("/api/map/unlock")
async def map_unlock():
    """手动消耗图碎解锁下一地点"""
    cnt = g.get_map_fragment_count()
    return {
        "fragment_count": cnt,
        "unlocked": g.get_unlocked_locations(),
        "message": f"当前持有 {cnt} 片图碎，可前往已解锁地点探索" if cnt == 0
                   else f"已解锁地点：{', '.join(g.get_unlocked_locations())}",
    }


# ════════════════════════════════════════════════
# 新手引导 API
# ════════════════════════════════════════════════
@app.get("/api/tutorial/status")
async def tutorial_status():
    return g.tutorial_status()

@app.post("/api/tutorial/start")
async def tutorial_start(req: g.TutorialStartReq, user_id: str = Query("default")):
    try:
        return g.tutorial_start(req.faction, user_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

@app.post("/api/tutorial/complete-step")
async def tutorial_complete_step(req: g.TutorialStepReq, user_id: str = Query("default")):
    return g.tutorial_complete_step(req.action)


# ════════════════════════════════════════════════
# TTS API（DashScope，目前禁用）
# ════════════════════════════════════════════════
@app.post("/api/tts")
async def tts(npc_name: str = Form(default="店小二"), text: str = Form(...)):
    # TTS 额度已用完，直接返回 None
    return {"audio_url": None}

@app.get("/audio/{filename}")
async def get_audio(filename: str):
    safe_name = os.path.basename(filename)
    audio_path = os.path.join(g.BASE_DIR, "audio", safe_name)
    if not os.path.exists(audio_path):
        raise HTTPException(status_code=404, detail="音频不存在")
    return FileResponse(audio_path, media_type="audio/mpeg")


# ════════════════════════════════════════════════
# 邮箱 API
# ════════════════════════════════════════════════
@app.get("/api/mailbox")
async def api_mailbox(user_id: str = Query(default="default")):
    """获取邮箱消息列表"""
    msgs = g.get_mailbox(user_id)
    unread = sum(1 for m in msgs if not m["read"])
    return {"messages": msgs, "unread": unread}


@app.post("/api/mailbox/read")
async def api_mailbox_read(req: g.MailboxReadReq):
    """标记消息已读"""
    g.mark_mail_read(req.user_id or "default", req.message_ids)
    return {"ok": True}


@app.delete("/api/mailbox/{msg_id}")
async def api_mailbox_delete(msg_id: str, user_id: str = Query(default="default")):
    """删除单条消息"""
    g.delete_mail_message(user_id, [msg_id])
    return {"ok": True}


@app.post("/api/mailbox/send")
async def api_mailbox_send(req: g.MailboxSendReq):
    """手动触发生成邮箱消息（用于测试）"""
    npc_name = req.npc_name
    if npc_name not in NPC_PROFILES:
        raise HTTPException(status_code=400, detail="NPC不存在")
    mot = g.chat.motivation_manager.get(npc_name)
    content = g.chat.generate_mail_message(npc_name, mot)
    g.add_mail_message(req.user_id or "default", npc_name, content, mot.get("mood", ""))
    return {"from_npc": npc_name, "content": content}


# ════════════════════════════════════════════════
# 事件引擎 API
# ════════════════════════════════════════════════
@app.post("/api/events/generate")
async def api_events_generate(npc_name: str = Form(default=""), count: int = Form(default=5)):
    """为单个/所有NPC生成事件"""
    em = g.chat.event_manager
    if em is None:
        raise HTTPException(status_code=503, detail="事件引擎未初始化")
    if npc_name:
        if npc_name not in NPC_PROFILES:
            raise HTTPException(status_code=400, detail="NPC不存在")
        events = em.generate_for_npc(npc_name, count)
        return {"npc": npc_name, "generated": count, "passed": len(events)}
    else:
        result = em.generate_for_all(count)
        return result


@app.get("/api/events/active")
async def api_events_active(npc_name: str = Query(default="")):
    """获取活跃事件"""
    em = g.chat.event_manager
    if em is None:
        raise HTTPException(status_code=503, detail="事件引擎未初始化")
    events = em.get_active_events(npc_name) if npc_name else em.get_active_events()
    return {"events": events, "count": len(events)}


@app.post("/api/events/resolve")
async def api_events_resolve(event_id: str = Form(...)):
    """标记事件为已处理"""
    em = g.chat.event_manager
    if em is None:
        raise HTTPException(status_code=503, detail="事件引擎未初始化")
    em.resolve_event(event_id)
    return {"ok": True}


@app.get("/api/events/stats")
async def api_events_stats():
    """获取事件过滤效果统计"""
    em = g.chat.event_manager
    if em is None:
        raise HTTPException(status_code=503, detail="事件引擎未初始化")
    return em.get_stats()


# ════════════════════════════════════════════════
# 围棋死活题 API
# ════════════════════════════════════════════════
from game_go import GoProblemManager, analyze_position, auto_solve

# 全局死活题管理器
_go_mgr = GoProblemManager()

@app.get("/api/go/problems")
async def go_problems():
    """获取死活题列表"""
    return _go_mgr.get_problems()

@app.get("/api/go/problem/{problem_id}")
async def go_problem(problem_id: str):
    """获取单个死活题数据（不含答案）"""
    p = _go_mgr.get_problem(problem_id)
    if not p:
        raise HTTPException(status_code=404, detail="题目不存在")
    return {
        "id": p["id"],
        "name": p["name"],
        "difficulty": p["difficulty"],
        "description": p["description"],
        "board_size": p["board_size"],
    }

@app.post("/api/go/start/{quest_id}/{problem_id}")
async def go_start(quest_id: str, problem_id: str):
    """开始一个死活题会话"""
    s = _go_mgr.start_session(quest_id, problem_id)
    if not s:
        raise HTTPException(status_code=404, detail="题目不存在")
    return s

@app.get("/api/go/status/{quest_id}")
async def go_status(quest_id: str):
    """获取死活题会话状态（页面刷新后恢复用）"""
    s = _go_mgr.get_session_status(quest_id)
    if not s:
        return {"active": False}
    return {"active": True, **s}

@app.post("/api/go/move/{quest_id}")
async def go_move(quest_id: str, col: int = Query(...), row: int = Query(...)):
    """落子验证"""
    r = _go_mgr.make_move(quest_id, col, row)
    return r

@app.post("/api/go/evaluate/{quest_id}")
async def go_evaluate(quest_id: str):
    """判定死活"""
    r = _go_mgr.evaluate(quest_id)
    return r

@app.post("/api/go/resolve/{quest_id}")
async def go_resolve(quest_id: str):
    """死活题通关，推进任务步骤 + 如果任务完成则发放奖励"""
    uid = "default"
    r = g.chat.resolve_go_step(quest_id)
    if "error" in r:
        raise HTTPException(status_code=400, detail=r["error"])

    reward_info = None
    if r.get("completed"):
        # 查找任务定义，发放实际奖励（与正常聊天完成任务的逻辑一致）
        from quest_data import ALL_QUESTS
        for qname, qdata in ALL_QUESTS.items():
            if qdata.get("qid") == quest_id:
                rd = qdata.get("reward_data", {})
                if rd.get("exp"):  g.exp += rd["exp"]
                if rd.get("silver"): g.silver += rd.get("silver", 0)
                if rd.get("items"):
                    for it in rd["items"]:
                        found = next((x for x in g.player_items if x["name"] == it["name"]), None)
                        if found:
                            found["count"] = found.get("count", 1) + it.get("count", 1)
                        else:
                            g.player_items.append(dict(it))
                if rd.get("intimacy"):
                    npc_name = qdata.get("npc_permission", ["风清扬"])[0]
                    g.chat.memory.update_relation(uid, npc_name, rd["intimacy"])
                reward_info = {
                    "title": r.get("title", qdata.get("title", "")),
                    "reward": r.get("reward", qdata.get("reward", "")),
                    "npc_line": r.get("npc_line", ""),
                    "exp": rd.get("exp", 0),
                    "silver": rd.get("silver", 0),
                    "items": rd.get("items", []),
                }
                break

    g.save_all_state()  # 持久化任务状态 + 奖励
    # 顶层透传 npc_line 和 reward 给前端直接用
    npc_line = r.get("npc_line", "")
    reward_text = r.get("reward", "")
    if reward_info and not npc_line:
        npc_line = reward_info.get("npc_line", "")
    if reward_info and not reward_text:
        reward_text = reward_info.get("reward", "")
    return {
        "completed": r.get("completed", False),
        "npc_line": npc_line,
        "reward": reward_text,
        "reward_info": reward_info,
    }

@app.post("/api/go/analyze")
async def go_analyze(data: dict):
    """独立分析工具：分析任意棋盘位置，返回推荐走法"""
    stones_b_raw = data.get("stones_b", [])
    stones_w_raw = data.get("stones_w", [])
    board_size = data.get("board_size", 19)
    color = data.get("color", "B")
    moves = data.get("moves", 5)

    stones_b = [tuple(int(x) for x in s.split(",")) for s in stones_b_raw]
    stones_w = [tuple(int(x) for x in s.split(",")) for s in stones_w_raw]
    results = analyze_position(stones_b, stones_w, board_size, color, moves)

    # 兼容旧返回格式（tuple → dict 转换兜底）
    if results and isinstance(results[0], (list, tuple)):
        return [{"coord": c, "visits": v, "winrate": wr} for c, v, wr in results]
    return results


@app.post("/api/go/auto-solve")
async def go_auto_solve(data: dict):
    """自动求解死活题（优先使用预计算正解序列，fallback genmove）
    请求体: {stones_b: ["0,4",...], stones_w: [...], board_size: 9,
             player_color: "B", max_moves: 50, problem_id: "tsume_001"}
    坐标: "col,row" row=0=top
    """
    stones_b_raw = data.get("stones_b", [])
    stones_w_raw = data.get("stones_w", [])
    board_size = data.get("board_size", 9)
    player_color = data.get("player_color", "B")
    max_moves = data.get("max_moves", 50)
    problem_id = data.get("problem_id")

    stones_b = [tuple(int(x) for x in s.split(",")) for s in stones_b_raw]
    stones_w = [tuple(int(x) for x in s.split(",")) for s in stones_w_raw]

    result = auto_solve(stones_b, stones_w, board_size, player_color,
                        max_moves, problem_id=problem_id)
    return result


@app.get("/api/go/benchmark")
async def go_benchmark():
    """Pregen vs Genmove 性能对比
    对每道死活题分别用 pregen 和纯 genmove 求解，对比耗时和结果
    """
    from game_go import TSUMEGO_PROBLEMS, auto_solve
    results = []
    for p in TSUMEGO_PROBLEMS:
        pid = p["id"]
        bs = p["board_size"]
        initial = p["initial"]

        # 初始局面转前端坐标
        stones_b = [(c, bs - 1 - r) for c, r in initial.get("B", [])]
        stones_w = [(c, bs - 1 - r) for c, r in initial.get("W", [])]

        # Pregen 模式（正常）
        r_pregen = auto_solve(stones_b, stones_w, bs, "B",
                              max_moves=15, problem_id=pid)
        # Genmove 模式（强制跳过预计算）
        r_genmove = auto_solve(stones_b, stones_w, bs, "B",
                               max_moves=15, problem_id=pid,
                               force_genmove=True)

        results.append({
            "id": pid,
            "name": p["name"],
            "difficulty": p["difficulty"],
            "pregen": {
                "solved": r_pregen["solved"],
                "elapsed_sec": r_pregen.get("elapsed_sec", 0),
                "moves": len(r_pregen.get("moves", [])),
                "summary": r_pregen.get("summary", ""),
            },
            "genmove": {
                "solved": r_genmove["solved"],
                "elapsed_sec": r_genmove.get("elapsed_sec", 0),
                "moves": len(r_genmove.get("moves", [])),
                "summary": r_genmove.get("summary", ""),
            },
        })
    return {"problems": results}


# ════════════════════════════════════════════════
# 诊断 API
# ════════════════════════════════════════════════
@app.get("/api/diag")
async def api_diag():
    """系统诊断报告"""
    em = g.chat.event_manager
    if em is None:
        return {"server": {"status": "事件引擎未初始化"}}
    return em.diag.report(em, g.chat)


@app.get("/api/events/benchmark")
async def api_events_benchmark(npc: str = None, count: int = 10):
    """三层评审效果对比：为指定NPC生成事件，返回原始事件+三层过滤诊断"""
    em = g.chat.event_manager
    if em is None:
        return {"error": "事件引擎未初始化"}
    return em.benchmark_generate(npc, count)


@app.get("/api/events/compare_modes")
async def api_compare_generation_modes(npc_count: int = 4, events_per: int = 3):
    """预生成 vs 实时生成对比：隔离模式(模拟实时) vs 全局模式(预生成)，检测矛盾数"""
    em = g.chat.event_manager
    if em is None:
        return {"error": "事件引擎未初始化"}
    return em.compare_generation_modes(npc_count, events_per)


# ════════════════════════════════════════════════
# 聊天记录持久化（页面刷新恢复用）
# ════════════════════════════════════════════════
@app.get("/api/chat/history")
async def get_chat_history():
    """获取所有 NPC 聊天记录"""
    return {"messages": g.chat_messages}

@app.post("/api/chat/history")
async def save_chat_history(data: dict):
    """保存聊天记录"""
    g.chat_messages = data.get("messages", {})
    g.save_chat_messages()
    return {"status": "ok"}


# ════════════════════════════════════════════════
# 启动
# ════════════════════════════════════════════════
if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8000, reload=False)
