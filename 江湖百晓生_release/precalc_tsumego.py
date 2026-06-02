"""
precalc_tsumego.py v4 — 死活题预计算（迭代式高visits + ownership验证）
每道题最多3轮迭代：PV走完 → 对手视角无杀招 → 通过
min_visits=3000, 对手分析=800 visits
"""

import sys, json
sys.path.insert(0, '.')

from game_go import (TSUMEGO_PROBLEMS, _engine, parse_gtp, _gtp_str,
                      _benson_check, _capture_after_move, _stones_from_board)

MAX_ROUNDS = 3
PLAYER_VISITS = 2000
OPP_VISITS = 600
OPP_KILL_THRESHOLD = 50  # 对手分析访问量低于此值视为无杀招


def _calc_zone(board, board_size, color="B"):
    xs, ys = [], []
    for y in range(board_size):
        for x in range(board_size):
            if board[y][x] == color:
                xs.append(x); ys.append(y)
    if not xs:
        return None
    return (range(max(0, min(xs) - 2), min(board_size, max(xs) + 3)),
            range(max(0, min(ys) - 2), min(board_size, max(ys) + 3)))


def _zone_ownership(ownership_arr, bs, zone):
    """统计zone内黑方归属度总和（>0.5 视为黑地盘）"""
    zone_x, zone_y = zone
    total = 0.0
    points = 0
    for y in zone_y:
        for x in zone_x:
            idx = y * bs + x
            if idx < len(ownership_arr):
                val = ownership_arr[idx]
                total += val
                if val > 0.5:
                    points += 1
    return total, points


def _check_opp_has_kill(board, bs, zone):
    """对手视角分析：zone内是否有有效杀招
    返回 (has_kill, best_move, visits)
    """
    sb, sw = _stones_from_board(board, bs)
    infos = _engine._analyze_raw(
        "W", bs, sb, sw,
        moves_count=3, force_zone=zone, max_visits=OPP_VISITS
    )
    if not infos:
        return False, "", 0

    top = infos[0]
    move = top.get("move", "")
    visits = top.get("visits", 0)

    if not move or move.upper() == "PASS" or visits < OPP_KILL_THRESHOLD:
        return False, move, visits

    return True, move, visits


def precalc_problem_iterative(problem):
    pid = problem["id"]
    bs = problem["board_size"]
    initial = problem["initial"]

    # 构建初始棋盘 (row=0=top)
    board = [["" for _ in range(bs)] for _ in range(bs)]
    for c, r in initial.get("B", []):
        board[bs - 1 - r][c] = "B"
    for c, r in initial.get("W", []):
        board[bs - 1 - r][c] = "W"

    zone = _calc_zone(board, bs, "B")
    if not zone:
        return {"id": pid, "error": "无玩家棋子", "full_sequence": [], "verified": False}

    full_sequence = []

    for round_num in range(MAX_ROUNDS):
        # ── 1. 玩家视角高visits分析 ──
        sb, sw = _stones_from_board(board, bs)
        data = _engine._analyze_raw(
            "B", bs, sb, sw,
            moves_count=5, force_zone=zone, max_visits=PLAYER_VISITS,
            include_ownership=True
        )
        if not data or isinstance(data, list):
            break

        move_infos = data.get("moveInfos", [])
        if not move_infos:
            break

        top = move_infos[0]
        pv = top.get("pv", [])
        visits = top.get("visits", 0)
        wr = top.get("winrate", 0.5)

        ownership = data.get("ownership", []) if isinstance(data, dict) else []
        if ownership:
            zone_own, zone_pts = _zone_ownership(ownership, bs, zone)
            print(f"  R{round_num+1}: PV={pv[:5]}... visits={visits} zone_own={zone_own:.1f} zone_pts={zone_pts}", flush=True)
        else:
            print(f"  R{round_num+1}: PV={pv[:5]}... visits={visits}", flush=True)

        if not pv:
            break

        # ── 2. 走完PV ──
        current_color = "B"
        for gtp_coord in pv:
            if gtp_coord.upper() == "PASS":
                current_color = "W" if current_color == "B" else "B"
                full_sequence.append({"color": current_color, "coord": "PASS"})
                continue

            try:
                col, row = parse_gtp(gtp_coord, bs)
            except (ValueError, IndexError):
                break

            if board[row][col] != "":
                break

            board[row][col] = current_color
            captured, _ = _capture_after_move(board, col, row, current_color, bs)
            full_sequence.append({
                "color": current_color, "coord": gtp_coord,
                "captures": len(captured)
            })
            current_color = "W" if current_color == "B" else "B"

        # ── 3. 更新zone并检查Benson ──
        zone = _calc_zone(board, bs, "B")
        if not zone:
            break

        alive, summary = _benson_check(board, "B", "W", zone, bs)
        if alive:
            print(f"    Benson判定活棋: {summary}", flush=True)
            break

        # ── 4. 对手视角：有无杀招？ ──
        has_kill, kill_move, kill_visits = _check_opp_has_kill(board, bs, zone)
        if not has_kill:
            # 对手无有效杀招 → 判定活棋！
            print(f"    对手无杀招 (top={kill_move}, visits={kill_visits}) → 活棋！", flush=True)
            alive = True
            break
        else:
            # 有杀招 → 在下一轮PV中考虑它
            print(f"    对手有杀招 {kill_move} (visits={kill_visits})", flush=True)
            # 将杀招作为对手应手记录
            try:
                kx, ky = parse_gtp(kill_move, bs)
                if board[ky][kx] == "":
                    board[ky][kx] = "W"
                    _capture_after_move(board, kx, ky, "W", bs)
                    full_sequence.append({
                        "color": "W", "coord": kill_move, "captures": 0
                    })
            except (ValueError, IndexError):
                pass
            zone = _calc_zone(board, bs, "B")

    # ── 终局验证 ──
    zone = _calc_zone(board, bs, "B")
    final_alive = alive  # 优先用循环内判定的alive状态
    final_summary = ""
    if zone and not final_alive:
        final_alive, final_summary = _benson_check(board, "B", "W", zone, bs)
        if not final_alive:
            # Benson没过，再用ownership/对手杀招双重检查
            has_kill, km, kv = _check_opp_has_kill(board, bs, zone)
            if not has_kill:
                final_alive = True
                final_summary = f"对手无杀招(verify), visits={kv}"
            else:
                sb, sw = _stones_from_board(board, bs)
                data = _engine._analyze_raw(
                    "B", bs, sb, sw,
                    moves_count=3, force_zone=zone, max_visits=1000,
                    include_ownership=True
                )
                if not isinstance(data, list) and data:
                    ownership = data.get("ownership", [])
                    zone_own, zone_pts = _zone_ownership(ownership, bs, zone)
                    if zone_pts >= 2:
                        final_alive = True
                        final_summary = f"ownership验证: {zone_pts}黑地盘"
    elif final_alive and not final_summary:
        final_summary = "对手无杀招判定"

    # 拆成玩家走和对手应
    player_moves = [m for m in full_sequence if m["color"] == "B"]
    opponent_moves = [m for m in full_sequence if m["color"] == "W"]

    print(f"  最终: {'活' if final_alive else '未活'}, {final_summary}")
    print(f"  序列: {len(full_sequence)}步 (P{len(player_moves)}/O{len(opponent_moves)})")

    return {
        "id": pid,
        "name": problem["name"],
        "difficulty": problem["difficulty"],
        "player_moves": player_moves,
        "opponent_responses": opponent_moves,
        "full_sequence": full_sequence,
        "verified": final_alive,
        "verification": final_summary,
        "rounds": round_num + 1,
    }


def main():
    results = []
    for p in TSUMEGO_PROBLEMS:
        print(f"\n{'='*50}")
        print(f"题目: {p['name']} ({p['id']})")
        print(f"{'='*50}")
        r = precalc_problem_iterative(p)
        results.append(r)

    # 保存完整版
    with open("tsumego_solutions.json", "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)

    # 保存精简版
    slim = {}
    for r in results:
        if "error" in r:
            continue
        slim[r["id"]] = {
            "player_moves": [m["coord"] for m in r.get("player_moves", [])],
            "opponent_responses": [m["coord"] for m in r.get("opponent_responses", [])],
            "verified": r["verified"],
        }
    with open("tsumego_solutions_slim.json", "w", encoding="utf-8") as f:
        json.dump(slim, f, ensure_ascii=False, indent=2)

    print(f"\n{'='*50}")
    print(f"结果汇总:")
    for r in results:
        status = "OK" if r.get("verified") else "FAIL"
        pm = len(r.get("player_moves", []))
        om = len(r.get("opponent_responses", []))
        err = r.get("error", "")
        ver = r.get("verification", "")
        rds = r.get("rounds", 0)
        print(f"  {r['id']}: {status} ({pm}P/{om}O, {rds}轮) {ver} {err}")


if __name__ == "__main__":
    main()
