"""
剧情节点批量增强脚本
对 events.db 中已有的 story_nodes 进行四个维度的增强：
1. importance_score 分配 (3-10，区分主线/支线/过渡)
2. 时间窗分层 (day_min/day_max 分三段)
3. impact_json 填充 (世界影响)
4. options_json 填充 (玩家选项，2-3个)

同时修复 category 标签错误、condition_edges 逻辑问题。
"""
import sqlite3
import json
import time
import sys
import os
import requests

# DeepSeek 配置
from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env"))

API_KEY = os.getenv("DEEPSEEK_API_KEY")
API_BASE = os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com")
API_URL = f"{API_BASE}/v1/chat/completions"

DB_PATH = os.path.join(os.path.dirname(__file__), "events", "events.db")

ENHANCE_PROMPT = """你是武侠游戏叙事设计师。请对以下 {total} 个已生成的江湖故事节点进行全面优化。

## 优化要求

### 1. importance_score (主线/支线区分)
给每个节点分配重要性分数(3-10)：
- 8-10: 直接推动打狗棒主线、重要NPC关系转折、重大冲突
- 5-7: 支线任务、角色塑造、日常事件
- 3-4: 氛围描写、无关紧要的小事

当前所有节点都标记为5.0，请根据实际内容重新分配。一个游戏世界里不应该所有事件同等重要。

### 2. day_min / day_max (时间窗分层)
根据事件在叙事中的位置分配天数窗口：
- 开场事件(1-3天): 玩家刚进入游戏就能遇到的小事件、八卦
- 中期事件(3-7天): 需要一定探索后才能触发的事件
- 后期事件(5+天): 剧情发展到一定阶段才会出现的重大事件
- 事件链上后续节点的 day_min 必须 > 前驱节点的 day_min

原则：不要让玩家第1天就遇到打狗棒真相或父女对峙这种大事件。

### 3. impact_json (世界影响)
事件触发后对游戏世界产生的影响。格式如下（根据事件内容选择性填写，不要全填）：
{{
  "faction_reputation": {{"丐帮": -5}}（可选：势力声望变化 -10到+10）
  "npc_relation": {{"洪七公": {{"欧阳克": -10}}}}（可选：NPC关系变化）
  "unlock_nodes": []（可选：解锁后续事件ID，填真实的 sn_xxx id）
  "world_state": {{"打狗棒传闻": "confirmed"}}（可选：世界状态变更）
}}

不要所有事件都填 impact。只有真正改变世界的事件才填。小事件可以留空 {{}}。

### 4. options_json (玩家交互选项)
为每个事件设计2-3个玩家选择项，格式：
[
  {{"text": "选项描述文本(15字内)", "result": {{"favor_change": -5或5, "trigger_next": "sn_xxx"或null}}, "hint": "选择后的简短提示"}},
  ...
]

选项类型参考：
- 插手/旁观：参与事件或置之不理
- 告知/隐瞒：把消息告诉相关NPC或保守秘密
- 帮助/利用：帮助事件中的NPC或从中渔利
- 调解/挑拨：缓和冲突或煽风点火

### 5. 修复逻辑问题
- 检查 category 标签：世界新闻用 world_news，NPC冲突用 npc_conflict，NPC个人行动用 npc_action
- 检查 condition_edges：事件链的前驱后继关系是否合理

## 输入节点
以下是需要优化的所有故事节点：
{nodes_json}

## 输出格式
输出一个JSON数组，每个元素对应输入节点，保留原始 id，只更新需要修改的字段：
[
  {{
    "id": "sn_xxxxx",
    "importance_score": 8,
    "day_min": 3,
    "day_max": 999,
    "impact_json": {{"npc_relation": {{"洪七公": {{"欧阳克": -10}}}}}},
    "options_json": [
      {{"text": "立即通知洪七公", "result": {{"favor_change": 5, "trigger_next": null}}, "hint": "洪七公对你的信任+5"}},
      {{"text": "先去白驼山庄暗中查探", "result": {{"favor_change": 0, "trigger_next": "sn_398538fd"}}, "hint": "或许能先找到线索"}}
    ],
    "category_修正": "npc_conflict",  // 如果原分类错了就在这里写正确的，没错就省略
    "reason": "重要性理由(一句话)"
  }}
]
"""


def get_nodes():
    """从数据库读取所有 story_nodes"""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    rows = conn.execute("SELECT * FROM story_nodes ORDER BY created_at").fetchall()
    conn.close()

    nodes = []
    for row in rows:
        d = dict(row)
        # 解析 JSON 字段
        for col in ["involved_npcs", "trigger_json", "options_json",
                     "condition_edges_json", "impact_json"]:
            if d.get(col) and isinstance(d[col], str):
                try:
                    d[col] = json.loads(d[col])
                except:
                    pass
        nodes.append(d)
    return nodes


import re

def _parse_json(raw_text):
    """鲁棒 JSON 解析 - 处理 LLM 常见输出格式错误"""
    text = raw_text.strip()
    # 去掉 markdown 代码块
    if text.startswith("```"):
        lines = text.split("\n")
        if lines[0].strip() in ("```json", "```"):
            lines = lines[1:]
        if lines[-1].strip() == "```":
            lines = lines[:-1]
        text = "\n".join(lines)

    # 策略1: 直接解析
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    # 策略2: 提取数组
    start = text.find("[")
    end = text.rfind("]") + 1
    if start >= 0 and end > start:
        try:
            return json.loads(text[start:end])
        except json.JSONDecodeError:
            pass

    # 策略3: 移除尾部逗号后重试
    try:
        cleaned = re.sub(r',\s*([}\]])', r'\1', text)
        start = cleaned.find("[")
        end = cleaned.rfind("]") + 1
        if start >= 0 and end > start:
            return json.loads(cleaned[start:end])
    except json.JSONDecodeError:
        pass

    # 策略4: 修复单引号问题
    try:
        import ast
        start = text.find("[")
        end = text.rfind("]") + 1
        if start >= 0 and end > start:
            return ast.literal_eval(text[start:end])
    except (SyntaxError, ValueError):
        pass

    return None


def _call_deepseek(prompt, model="deepseek-chat"):
    """直接 HTTP 调用 DeepSeek API"""
    headers = {
        "Authorization": f"Bearer {API_KEY}",
        "Content-Type": "application/json"
    }
    body = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.3,
        "max_tokens": 4096,
    }
    resp = requests.post(API_URL, json=body, headers=headers, timeout=120)
    if resp.status_code != 200:
        raise Exception(f"API {resp.status_code}: {resp.text[:200]}")
    data = resp.json()
    return data["choices"][0]["message"]["content"]


def enhance_nodes(nodes):
    """分批调用 DeepSeek 增强节点，每批8个"""

    BATCH_SIZE = 4
    all_enhanced = []
    total = len(nodes)

    for batch_idx in range(0, total, BATCH_SIZE):
        batch = nodes[batch_idx:batch_idx + BATCH_SIZE]
        batch_num = batch_idx // BATCH_SIZE + 1
        total_batches = (total + BATCH_SIZE - 1) // BATCH_SIZE

        simplified = []
        for n in batch:
            simplified.append({
                "id": n["id"],
                "title": n["title"],
                "category": n["category"],
                "from_npc": n["from_npc"],
                "summary": n["summary"],
                "location": n["location"],
                "involved_npcs": n.get("involved_npcs", []),
                "trigger_json": n.get("trigger_json", {}),
                "condition_edges_json": n.get("condition_edges_json", []),
                "quality_score": n["quality_score"],
                "importance_score": n["importance_score"],
                "day_min": n["day_min"],
                "day_max": n["day_max"],
            })

        nodes_json = json.dumps(simplified, ensure_ascii=False, indent=2)
        prompt = ENHANCE_PROMPT.format(total=len(batch), nodes_json=nodes_json)

        print(f"  [{batch_num}/{total_batches}] 增强 {len(batch)} 个节点 ({batch[0]['id']}...{batch[-1]['id']})")
        sys.stdout.flush()

        try:
            raw = _call_deepseek(prompt)
        except Exception as e:
            print(f"  批次 {batch_num} API 失败: {e}，重试...")
            sys.stdout.flush()
            time.sleep(3)
            try:
                raw = _call_deepseek(prompt)
            except Exception as e2:
                print(f"  批次 {batch_num} 重试也失败: {e2}，跳过")
                sys.stdout.flush()
                continue

        result = _parse_json(raw)
        if result is None:
            debug_path = os.path.join(os.path.dirname(__file__), "state", f"enhance_batch_{batch_num}.txt")
            os.makedirs(os.path.dirname(debug_path), exist_ok=True)
            with open(debug_path, "w", encoding="utf-8") as f:
                f.write(raw)
            print(f"  批次 {batch_num} JSON 解析失败，原始输出: {debug_path}")
            sys.stdout.flush()
            continue

        if isinstance(result, dict):
            result = [result]

        print(f"  批次 {batch_num} 成功解析 {len(result)} 个")
        sys.stdout.flush()
        all_enhanced.extend(result)

    print(f"\n[Enhance] 总计 {len(all_enhanced)}/{total} 个节点增强成功")
    sys.stdout.flush()
    return all_enhanced if all_enhanced else None


def apply_enhancements(enhanced_nodes):
    """将增强数据写回数据库"""
    conn = sqlite3.connect(DB_PATH)
    updated = 0

    for en in enhanced_nodes:
        nid = en.get("id")
        if not nid:
            continue

        updates = {}
        if "importance_score" in en:
            updates["importance_score"] = en["importance_score"]
        if "day_min" in en:
            updates["day_min"] = en["day_min"]
        if "day_max" in en:
            updates["day_max"] = en["day_max"]
        if "impact_json" in en and en["impact_json"] is not None:
            updates["impact_json"] = json.dumps(en["impact_json"], ensure_ascii=False)
        if "options_json" in en and en["options_json"] is not None:
            updates["options_json"] = json.dumps(en["options_json"], ensure_ascii=False)
        if "category_修正" in en:
            updates["category"] = en["category_修正"]

        if not updates:
            continue

        set_clause = ", ".join(f"{k}=?" for k in updates)
        values = list(updates.values()) + [nid]
        conn.execute(f"UPDATE story_nodes SET {set_clause} WHERE id=?", values)
        updated += 1

    conn.commit()
    conn.close()
    print(f"[Enhance] 更新了 {updated} 个节点")


def validate_nodes():
    """验证增强后的节点是否有明显错误"""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    rows = conn.execute("SELECT id, title, importance_score, day_min, day_max, options_json, impact_json, category FROM story_nodes ORDER BY importance_score DESC").fetchall()
    conn.close()

    print("\n" + "=" * 60)
    print("验证报告")
    print("=" * 60)

    scores = [r["importance_score"] for r in rows]
    min_s, max_s = min(scores), max(scores)
    print(f"importance_score 分布: {min_s}~{max_s}, 5分数量: {scores.count(5)}/{len(scores)}")

    # 时间窗检查
    max_day_issues = [r for r in rows if r["day_max"] < r["day_min"]]
    if max_day_issues:
        print(f"警告: {len(max_day_issues)} 个节点 day_max < day_min: {[r['id'] for r in max_day_issues]}")

    # options 检查
    empty_options = sum(1 for r in rows if not r["options_json"] or r["options_json"] == "[]")
    print(f"无选项的节点: {empty_options}/{len(rows)}")

    # impact 检查
    empty_impact = sum(1 for r in rows if not r["impact_json"] or r["impact_json"] == "{}")
    print(f"无影响的节点: {empty_impact}/{len(rows)}")

    # 打狗棒主线节点
    print("\n高分节点 (>=8):")
    for r in rows:
        if r["importance_score"] >= 8:
            opts = json.loads(r["options_json"]) if r["options_json"] and r["options_json"] != "[]" else []
            print(f"  [{r['importance_score']}] {r['title']} (day {r['day_min']}-{r['day_max']}, {r['category']}, {len(opts)}选项)")


def main():
    print("=" * 60)
    print("剧情节点批量增强")
    print("=" * 60)

    # 1. 读取
    print("\n[1/4] 读取现有节点...")
    nodes = get_nodes()
    if not nodes:
        print("没有找到任何 story_nodes，请先运行 pregen.py")
        sys.exit(1)
    print(f"  找到 {len(nodes)} 个节点")

    # 2. 增强
    print("\n[2/4] 调用 DeepSeek 增强...")
    enhanced = enhance_nodes(nodes)
    if not enhanced:
        print("增强失败，保留现有数据")
        sys.exit(1)

    # 3. 写入
    print("\n[3/4] 写回数据库...")
    apply_enhancements(enhanced)

    # 4. 验证
    print("\n[4/4] 验证结果...")
    validate_nodes()

    print("\n" + "=" * 60)
    print("增强完成！运行 python view_db.py 查看详情")
    print("=" * 60)


if __name__ == "__main__":
    main()
