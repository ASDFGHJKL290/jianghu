"""
post_process_chains.py — 链数据后处理脚本
用修正代替重新生成，对已有 story_nodes 做三项清理：
1. 重新编号：同 chain_id 内 step 连续递增 (0, 1, 2...)
2. 丢弃孤儿：单节点链 → 置空 chain_id
3. 重填 condition_edges：非末节点指向正确下一步

安全：只改 chain_id / chain_step / condition_edges_json 三个字段
不影响节点内容、quality_score、trigger_json
"""

import sqlite3
import json
import os
import shutil
from datetime import datetime

DB_PATH = os.path.join(os.path.dirname(__file__), "events", "events.db")

# ── 第零步：备份 ────────────────────────────────
backup = DB_PATH + ".bak." + datetime.now().strftime("%Y%m%d_%H%M%S")
shutil.copy2(DB_PATH, backup)
print(f"[备份] {backup}")

db = sqlite3.connect(DB_PATH)
cur = db.cursor()

# ── 第一步：收集所有链 ──────────────────────────
cur.execute("""
    SELECT chain_id, chain_step, id, title, from_npc, location, condition_edges_json
    FROM story_nodes
    WHERE chain_id != '' AND chain_id IS NOT NULL
    ORDER BY chain_id, chain_step, created_at
""")
rows = cur.fetchall()

# 按 chain_id 分组
chains = {}
for cid, step, nid, title, npc, loc, edges in rows:
    chains.setdefault(cid, []).append((step, nid, title, npc, loc, edges))

print(f"\n[扫描] 共 {len(chains)} 条链，{len(rows)} 个节点")

# ── 第二步：处理每条链 ──────────────────────────
fixed_count = 0
orphan_count = 0
edge_fixed = 0

for cid, nodes in sorted(chains.items()):
    # 按原 step 排序，同 step 按 id 字典序排
    nodes.sort(key=lambda x: (x[0], x[1]))

    if len(nodes) == 1:
        nid = nodes[0][1]
        cur.execute("UPDATE story_nodes SET chain_id = '' WHERE id = ?", (nid,))
        orphan_count += 1
        print(f"  ⚪ [{cid}] 单节点孤儿 → 置空 ({nodes[0][2]})")
        continue

    # 多节点链：重新编号
    for new_step, (old_step, nid, title, npc, loc, edges) in enumerate(nodes):
        if old_step != new_step:
            cur.execute("UPDATE story_nodes SET chain_step = ? WHERE id = ?", (new_step, nid))
            fixed_count += 1
            print(f"    [{cid}]「{title}」 {old_step} → {new_step}")

    # 重填 condition_edges
    for i in range(len(nodes)):
        nid = nodes[i][1]
        title = nodes[i][2]
        is_last = (i == len(nodes) - 1)
        if is_last:
            # 末节点清空边
            cur.execute("UPDATE story_nodes SET condition_edges_json = '[]' WHERE id = ?", (nid,))
            print(f"    [{cid}]「{title}」末节点，清空边")
        else:
            next_npc = nodes[i+1][3]
            next_loc = nodes[i+1][4]
            next_title = nodes[i+1][2]
            new_edges = json.dumps([{
                "condition": f"chain_complete('{cid}_step{i}')",
                "target_npc": next_npc,
                "target_location": next_loc,
                "hint": f"下一步：去找{next_npc}（{next_title}）",
                "score": 10.0,
                "source": "post_process_chain"
            }], ensure_ascii=False)
            cur.execute("UPDATE story_nodes SET condition_edges_json = ? WHERE id = ?", (new_edges, nid))
            edge_fixed += 1
            print(f"    [{cid}]「{title}」→ {next_title}({next_npc}@{next_loc})")

db.commit()

# ── 第三步：报告 ────────────────────────────────
print(f"\n{'='*50}")
print(f"   孤儿链丢弃: {orphan_count}")
print(f"   step 重编号: {fixed_count}")
print(f"   边重填:     {edge_fixed}")
print(f"{'='*50}")

# 验证结果
cur.execute("""
    SELECT chain_id, COUNT(*), GROUP_CONCAT(chain_step || ':' || title, ' → ')
    FROM story_nodes
    WHERE chain_id != '' AND chain_id IS NOT NULL
    GROUP BY chain_id
    ORDER BY chain_id
""")
print(f"\n[最终状态]")
for cid, cnt, steps in cur.fetchall():
    print(f"  📌 {cid} ({cnt}节点): {steps}")

db.close()
print("\n✅ 完成")
