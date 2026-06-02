"""全部 events.db 数据查看脚本"""
import sqlite3
import json

DB_PATH = r"C:\Users\aaa\PycharmProjects\day25\江湖百晓生_vue\events\events.db"

def print_separator(title):
    print(f"\n{'='*80}")
    print(f"  {title}")
    print(f"{'='*80}")

def print_table_data(conn, table, json_cols=None):
    """打印表结构和所有数据，json_cols 中的列会格式化展开"""
    if json_cols is None:
        json_cols = []

    cols = [c[1] for c in conn.execute(f"PRAGMA table_info({table})")]
    rows = conn.execute(f"SELECT * FROM {table}").fetchall()
    count = len(rows)

    print_separator(f"{table} ({count} rows)")
    print(f"  列: {', '.join(cols)}")
    print("-" * 80)

    for i, row in enumerate(rows):
        print(f"\n--- [行 {i+1}/{count}] ---")
        for j, col in enumerate(cols):
            val = row[j]
            if col in json_cols and val:
                try:
                    parsed = json.loads(val)
                    print(f"  {col}:")
                    print(json.dumps(parsed, ensure_ascii=False, indent=4))
                    continue
                except (json.JSONDecodeError, TypeError):
                    pass
            if isinstance(val, str) and len(val) > 200:
                print(f"  {col}: {val[:200]}...（总长{len(val)}字符）")
            else:
                print(f"  {col}: {val}")

def main():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row

    # 1. 总览
    tables = conn.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name").fetchall()
    print_separator("数据库总览")
    for t in tables:
        name = t[0]
        count = conn.execute(f"SELECT COUNT(*) FROM {name}").fetchone()[0]
        print(f"  {name}: {count} 行")

    # 2. 逐表打印
    # JSON 列：这些列存的是 JSON 字符串，需要格式化展示
    json_cols_map = {
        "events": ["related_npcs", "related_locations", "flags"],
        "story_nodes": ["involved_npcs", "trigger_json", "options_json",
                        "condition_edges_json", "impact_json"],
        "npc_experience_log": [],
        "npc_reflections": ["related_npcs"],
    }

    for table in [t[0] for t in tables]:
        print_table_data(conn, table, json_cols_map.get(table, []))

    conn.close()
    print(f"\n{'='*80}")
    print("  全部数据打印完毕")

if __name__ == "__main__":
    main()
