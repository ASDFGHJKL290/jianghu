# -*- coding: utf-8 -*-
"""
game_go.py — 围棋死活题 & KataGo 分析引擎
死活题验证：subprocess启动KataGo analysis模式，通过前5推荐是否离开目标区域判定死活
"""

import subprocess
import json
import os
import time
import threading
from collections import deque
from pathlib import Path
from typing import Optional
import copy

# ── KataGo 路径 ──────────────────────────────────────────
KATAGO_DIR = Path(os.environ.get("KATAGO_DIR", str(Path(__file__).parent / "katago")))
KATAGO_EXE  = KATAGO_DIR / "katago.exe"
KATAGO_MODEL = KATAGO_DIR / "kata1-b18c384nbt.bin.gz"
KATAGO_CFG  = KATAGO_DIR / "default_gtp.cfg"

# ── 死活题题库 ──────────────────────────────────────────
# 坐标格式: (col, row) 0-based, col=A=0, row=0=bottom
# solution: [(color, col, row), ...] — 每步指定谁落子
#   "B" = 玩家（解题方），"W" = 对手（自动应手）
# 玩家只走"B"步，对手"W"步自动落子
TSUMEGO_PROBLEMS = [
    {
        "id": "tsume_001",
        "name": "角部活棋·初",
        "difficulty": "入门",
        "description": "黑先活。角部被围，如何做出两只眼？",
        "board_size": 9,
        "initial": {
            "B": [(2,2), (2,3), (3,2)],       # C3, C4, D3
            "W": [(2,4), (3,3), (3,4), (4,2), (4,3), (4,4)],  # C5, D4, D5, E3, E4, E5
        },
        "solution": [("B", 1, 2)],  # 黑B2做活
        "hint": "在二路托一个，试试扩大眼位。",
    },
    {
        "id": "tsume_002",
        "name": "边路活棋·二",
        "difficulty": "简单",
        "description": "黑先活。黑棋在边上被围，需要找到做活要点。",
        "board_size": 9,
        "initial": {
            "B": [(3,2), (3,3), (4,2), (4,3)],
            "W": [(2,2), (2,3), (2,4), (3,4), (4,4), (5,2), (5,3), (5,4)],
        },
        "solution": [("B", 4, 1)],  # E2
        "hint": "往下二路大飞一个，扩大根据地。",
    },
    {
        "id": "tsume_003",
        "name": "中央突围·三",
        "difficulty": "中等",
        "description": "黑先活。三面被围，唯有一线生机。",
        "board_size": 9,
        "initial": {
            "B": [(3,3), (4,3), (5,3), (4,4)],
            "W": [(3,4), (4,5), (5,4), (6,3), (3,2), (4,2), (5,2)],
        },
        "solution": [("B", 4, 6)],  # E7
        "hint": "不要着急做眼，先向中央出头。",
    },
]

# ── 预计算正解序列 ──────────────────────────────────────
_PREGEN: dict = {}  # {problem_id: {"player_moves": [...], "opponent_responses": [...]}}

def _load_pregen():
    """加载预计算的死活题正解序列"""
    global _PREGEN
    try:
        path = os.path.join(os.path.dirname(__file__), "tsumego_solutions_slim.json")
        if os.path.exists(path):
            with open(path, "r", encoding="utf-8") as f:
                _PREGEN = json.load(f)
    except Exception:
        pass

_load_pregen()

def get_pregen(problem_id: str) -> tuple:
    """获取预计算正解: (player_moves, opponent_responses)
    未找到时返回 (None, None)
    """
    sol = _PREGEN.get(problem_id)
    if sol:
        return sol.get("player_moves", []), sol.get("opponent_responses", [])
    return None, None

# ── SGF/棋盘坐标工具 ──────────────────────────────────
_COL_NAMES = "ABCDEFGHJKLMNOPQRST"

def _gtp_str(col: int, row: int, board_size: int = 9) -> str:
    """(0-based col, 0-based row_from_top) → 'C3' 格式GTP坐标
    GTP坐标中 row 从底部开始，所以需要翻转
    """
    gtp_row = board_size - row  # row=0(top) → gtp_row=size(bottom)
    return f"{_COL_NAMES[col]}{gtp_row}"

def parse_gtp(coord: str, board_size: int = 9):
    """'C3' → (col, row_from_top) 0-based
    GTP坐标中 row 从底部开始，翻转后得到 board 用的 row_from_top
    """
    col = _COL_NAMES.index(coord[0].upper())
    gtp_row = int(coord[1:])  # 1-based from bottom
    row = board_size - gtp_row  # 0-based from top
    return col, row

def _is_move_in_zone(coord: str, zone: tuple, board_size: int = 9) -> bool:
    """检查GTP坐标是否在目标区域内
    zone: (x_range, y_range) 其中坐标是board坐标(row=0=top)
    """
    if not coord or coord.upper() == "PASS":
        return False
    try:
        col, row = parse_gtp(coord, board_size)
        x_range, y_range = zone
        return col in x_range and row in y_range
    except Exception:
        return False

# ── 提子逻辑 ──────────────────────────────────────────

def _find_group(x: int, y: int, color_set: set, size: int) -> set:
    """Flood Fill找连通块"""
    group = set()
    stack = [(x, y)]
    while stack:
        cx, cy = stack.pop()
        if (cx, cy) in group or (cx, cy) not in color_set:
            continue
        group.add((cx, cy))
        for nx, ny in [(cx-1,cy),(cx+1,cy),(cx,cy-1),(cx,cy+1)]:
            if 0 <= nx < size and 0 <= ny < size:
                stack.append((nx, ny))
    return group

def _group_liberties(group: set, enemy: set, size: int) -> int:
    """计算一个连通块的气"""
    visited = set()
    libs = 0
    for gx, gy in group:
        for nx, ny in [(gx-1,gy),(gx+1,gy),(gx,gy-1),(gx,gy+1)]:
            if 0 <= nx < size and 0 <= ny < size:
                if (nx, ny) not in (group | enemy) and (nx, ny) not in visited:
                    visited.add((nx, ny))
                    libs += 1
    return libs

def _capture_after_move(board: list, col: int, row: int, color: str, board_size: int) -> tuple:
    """落子后执行提子逻辑（修改board），返回 (被提棋子列表, 劫点或None)"""
    # 收集棋盘上黑白棋子位置
    b_set, w_set = set(), set()
    for y in range(board_size):
        for x in range(board_size):
            if board[y][x] == "B":
                b_set.add((x, y))
            elif board[y][x] == "W":
                w_set.add((x, y))

    my_set = b_set if color == "B" else w_set
    opp_set = w_set if color == "B" else b_set

    # 检查对方棋子是否有被提的
    to_remove = set()
    for nx, ny in [(col-1,row),(col+1,row),(col,row-1),(col,row+1)]:
        if 0 <= nx < board_size and 0 <= ny < board_size:
            if (nx, ny) in opp_set:
                opp_group = _find_group(nx, ny, opp_set, board_size)
                if opp_group and opp_group.isdisjoint(to_remove):
                    libs = _group_liberties(opp_group, my_set, board_size)
                    if libs == 0:
                        to_remove |= opp_group

    # 移除被提的棋子
    for rx, ry in to_remove:
        board[ry][rx] = ""

    # 自杀检测：落子后自己的连通块气为0 → 移除（除非已经提了对方的子）
    if not to_remove:
        my_group = _find_group(col, row, my_set | {(col, row)}, board_size)
        if my_group:
            libs = _group_liberties(my_group, opp_set, board_size)
            if libs == 0:
                for gx, gy in my_group:
                    board[gy][gx] = ""

    # 劫检测：如果只提了一子，且提子的那颗棋只剩1气（被提的位置就是劫）
    ko_point = None
    if len(to_remove) == 1:
        removed = list(to_remove)[0]
        # 重新获取当前棋盘棋子位置
        cur_b, cur_w = set(), set()
        for y in range(board_size):
            for x in range(board_size):
                if board[y][x] == "B":
                    cur_b.add((x, y))
                elif board[y][x] == "W":
                    cur_w.add((x, y))
        cur_my = cur_b if color == "B" else cur_w
        cur_opp = cur_w if color == "B" else cur_b
        # 找提子那颗棋的连通块
        capturer_group = _find_group(col, row, cur_my, board_size)
        if capturer_group:
            libs = _group_liberties(capturer_group, cur_opp, board_size)
            if libs == 1:
                # 唯一的1气就是被提的位置 → 形成劫
                ko_point = removed

    return list(to_remove), ko_point


# ── KataGo 常驻进程（模型只加载一次，分析毫秒级响应） ──────────────────
class KataGoEngine:
    """常驻 analysis 进程，避免每次请求重新加载模型"""

    def __init__(self):
        self._proc = None
        self._lock = threading.Lock()

    def _ensure_proc(self):
        """确保 Katago analysis 进程在运行"""
        if self._proc is not None and self._proc.poll() is None:
            return  # 进程仍存活

        if not KATAGO_EXE.exists():
            raise FileNotFoundError(f"KataGo not found: {KATAGO_EXE}")
        if not KATAGO_MODEL.exists():
            raise FileNotFoundError(f"Model not found: {KATAGO_MODEL}")

        # 启动常驻 analysis 进程
        self._proc = subprocess.Popen(
            [str(KATAGO_EXE), "analysis",
             "-config", str(KATAGO_DIR / "analysis_example.cfg"),
             "-model", str(KATAGO_MODEL),
             "-override-config", "numAnalysisThreads=2,warnUnusedFields=false"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            cwd=str(KATAGO_DIR),
            bufsize=0,  # 无缓冲
        )

    def stop(self):
        if self._proc:
            try:
                self._proc.stdin.close()
                self._proc.wait(timeout=5)
            except Exception:
                self._proc.kill()
            self._proc = None

    def _run(self, cmds: list, timeout: float = 120) -> str:
        """GTP 模式（保留兼容，偶尔用）"""
        if not KATAGO_EXE.exists():
            raise FileNotFoundError(f"KataGo not found: {KATAGO_EXE}")
        if not KATAGO_MODEL.exists():
            raise FileNotFoundError(f"Model not found: {KATAGO_MODEL}")
        gtp_input = "\n".join(cmds) + "\nquit\n"
        try:
            r = subprocess.run(
                [str(KATAGO_EXE), "gtp",
                 "-model", str(KATAGO_MODEL),
                 "-config", str(KATAGO_CFG)],
                input=gtp_input.encode("utf-8"),
                capture_output=True,
                cwd=str(KATAGO_DIR),
                timeout=timeout,
            )
            return r.stdout.decode("utf-8", errors="replace")
        except subprocess.TimeoutExpired:
            return ""
        except Exception as e:
            return f"ERR:{e}"

    def _query_analysis(self, query: dict, max_visits: int = 500) -> dict:
        """向常驻进程发送一次 analysis 查询，返回完整 JSON 响应"""
        with self._lock:
            for attempt in range(2):
                try:
                    self._ensure_proc()
                    payload = (json.dumps(query) + "\n").encode("utf-8")
                    self._proc.stdin.write(payload)
                    self._proc.stdin.flush()

                    # 读取响应行，直到拿到有效 JSON
                    start = time.time()
                    while (time.time() - start) < (60 if max_visits > 500 else 30):
                        line = self._proc.stdout.readline().decode("utf-8", errors="replace").strip()
                        if not line:
                            # 进程可能挂了
                            if self._proc.poll() is not None:
                                break  # 退出内层循环，走重试
                            continue
                        try:
                            data = json.loads(line)
                            if "error" in data:
                                continue
                            return data
                        except json.JSONDecodeError:
                            continue

                    # 超时或进程退出，重启进程重试一次
                    self.stop()
                except (BrokenPipeError, OSError):
                    self.stop()  # 进程挂了，重启

            raise TimeoutError("KataGo 分析超时")

    def _analyze_raw(self, color: str, board_size: int = 9,
                     stones_b: list = None, stones_w: list = None,
                     moves_count: int = 5,
                     avoid_coord: str = None,
                     force_zone: tuple = None,
                     max_visits: int = 500,
                     kill_mode: bool = False,
                     include_ownership: bool = False):
        """底层analysis调用，返回moveInfos列表（未过滤）；include_ownership=True时返回完整dict
        kill_mode=True: 压制目数权重专注死活（用于死活题判定）
        """
        initial_stones = []
        for c, r in (stones_b or []):
            initial_stones.append(["B", _gtp_str(c, r, board_size)])
        for c, r in (stones_w or []):
            initial_stones.append(["W", _gtp_str(c, r, board_size)])

        query = {
            "id": "go_analyze",
            "rules": "tromp-taylor",
            "komi": 6.5,
            "boardXSize": board_size,
            "boardYSize": board_size,
            "initialPlayer": color,
            "initialStones": initial_stones,
            "moves": [],
            "analyzeTurns": [0],
            "maxVisits": max_visits,
        }
        if include_ownership:
            query["includeOwnership"] = True
        if kill_mode:
            query["overrideSettings"] = {
                "staticScoreUtilityFactor": 0.001,
                "dynamicScoreUtilityFactor": 0.001,
                "winLossUtilityFactor": 1.0,
            }

        avoid_list = []
        if avoid_coord:
            avoid_list.append({
                "player": color,
                "moves": [avoid_coord],
                "untilDepth": 10,
            })
        if force_zone:
            target_x_range, target_y_range = force_zone
            moves_to_avoid = []
            for x in range(board_size):
                for y in range(board_size):
                    if not (x in target_x_range and y in target_y_range):
                        gtp = _gtp_str(x, y, board_size)
                        moves_to_avoid.append(gtp)
            if moves_to_avoid:
                avoid_list.append({
                    "player": color,
                    "moves": moves_to_avoid,
                    "untilDepth": 100,
                })
        if avoid_list:
            query["avoidMoves"] = avoid_list

        try:
            data = self._query_analysis(query, max_visits=max_visits)
            if include_ownership:
                return data
            return data.get("moveInfos", [])
        except Exception as e_ana:
            import sys
            sys.stderr.write(f"[KataGo _analyze_raw] 失败: {e_ana}\n")
        return {} if include_ownership else []

    def evaluate_life_death(self, color: str, board_size: int = 9,
                            stones_b: list = None, stones_w: list = None,
                            board: list = None,
                            force_zone: tuple = None) -> dict:
        """判定玩家大龙死活（KataGo前5推荐法）
        逻辑：让KataGo以对手视角在目标区域内思考，如果前5推荐全部离开目标区域（或找不到推荐），判活
        force_zone: (x_range, y_range) 固定杀棋区域
        """
        player_stones = set((stones_b if color == "B" else stones_w) or [])
        if not player_stones:
            return {"alive": False, "winrate": 0.5, "eyes": 0, "summary": "未有棋子"}

        if force_zone:
            target_x_range, target_y_range = force_zone
        else:
            xs = [s[0] for s in player_stones]
            ys = [s[1] for s in player_stones]
            target_x_range = range(max(0, min(xs) - 2), min(board_size, max(xs) + 3))
            target_y_range = range(max(0, min(ys) - 2), min(board_size, max(ys) + 3))

        # 在zone内找杀棋，只看对手是否有高质量杀棋着法
        opp_color = "W" if color == "B" else "B"
        candidates = self._best_kill_move(opp_color, board_size, stones_b, stones_w,
                                         force_zone=(target_x_range, target_y_range))

        if not candidates or candidates[0]["visits"] < 5:
            return {"alive": True, "winrate": 0.8, "eyes": 0,
                    "summary": "活了！KataGo在局部找不到有效杀棋"}
        else:
            return {"alive": False, "winrate": 0.3, "eyes": 0,
                    "summary": f"KataGo找到杀棋着法{candidates[0]['coord']}，还没活"}

    # ── 高级接口 ──

    def genmove(self, color: str, board_size: int = 9,
                stones_b: list = None, stones_w: list = None) -> str:
        """设置棋盘并生成一手棋，返回 GTP 坐标字符串"""
        cmds = [f"boardsize {board_size}", "clear_board"]
        for s in (stones_b or []):
            cmds.append(f"play B {_gtp_str(s[0], s[1], board_size)}")
        for s in (stones_w or []):
            cmds.append(f"play W {_gtp_str(s[0], s[1], board_size)}")
        cmds.append(f"genmove {color}")
        raw = self._run(cmds)
        for line in raw.split("\n"):
            line = line.strip()
            if line.startswith("=") and not line.startswith("= "):
                continue
            if line.startswith("= "):
                move = line[2:].strip()
                if move and move != "resign" and move != "Pass":
                    return move
        return ""

    def analyze(self, color: str, board_size: int = 9,
                stones_b: list = None, stones_w: list = None,
                moves_count: int = 5) -> list:
        """分析位置，返回推荐走法列表（含PV）"""
        move_infos = self._analyze_raw(color, board_size, stones_b, stones_w,
                                       moves_count=moves_count, max_visits=500)
        results = []
        for info in move_infos[:moves_count]:
            coord = info.get("move", "")
            if not coord or coord.upper() == "PASS":
                continue
            visits = info.get("visits", 0)
            winrate = info.get("winrate", 0.5)
            if color == "W":
                winrate = 1.0 - winrate
            pv = info.get("pv", [])[:15]
            results.append({
                "coord": coord,
                "visits": visits,
                "winrate": winrate,
                "pv": pv,
            })
        results.sort(key=lambda x: -x["visits"])
        return results

    def validate_move(self, color: str, move_coord: str,
                      stones_b: list, stones_w: list,
                      board_size: int = 9) -> dict:
        """验证落子是否与KataGo推荐一致"""
        best = self.genmove(color, board_size, stones_b, stones_w)
        if not best:
            return {"correct": False, "best_move": None, "reason": "KataGo分析超时"}
        is_correct = (move_coord.upper() == best.upper())
        return {
            "correct": is_correct,
            "best_move": best,
            "reason": "正确！" if is_correct else f"试试 {best}",
        }

    def _best_kill_move(self, color: str, board_size: int = 9,
                        stones_b: list = None, stones_w: list = None,
                        avoid_coord: str = None,
                        force_zone: tuple = None) -> list:
        """找出最佳杀棋着法（压制目数权重，专注死活）
        返回推荐着法列表 [{coord, visits, winrate, scoreLead}, ...]，按访问量降序
        force_zone: (x_range, y_range) 强制KataGo只考虑该区域内的着法
        """
        move_infos = self._analyze_raw(color, board_size, stones_b, stones_w,
                                       moves_count=10, avoid_coord=avoid_coord,
                                       force_zone=force_zone, max_visits=300, kill_mode=True)
        results = []
        for info in move_infos:
            coord = info.get("move", "")
            if coord and coord.upper() != "PASS":
                results.append({
                    "coord": coord,
                    "visits": info.get("visits", 0),
                    "winrate": info.get("winrate", 0.5),
                    "scoreLead": info.get("scoreLead", 0),
                })
        if results:
            results.sort(key=lambda x: -x["visits"])
        return results


# ── 全局引擎实例 ──────────────────────────────────────────
_engine = KataGoEngine()


# ── Benson 死活判定（独立函数） ──────────────────────────────

def _stones_from_board(board: list, board_size: int) -> tuple:
    """从棋盘提取黑白棋子坐标列表"""
    sb, sw = [], []
    for y in range(board_size):
        for x in range(board_size):
            if board[y][x] == "B":
                sb.append((x, y))
            elif board[y][x] == "W":
                sw.append((x, y))
    return sb, sw


def _benson_check(board: list, pc: str, oc: str, zone: tuple, bs: int) -> tuple:
    """Benson算法判定死活（独立函数，供GoProblemManager和auto_solve共用）
    返回 (is_alive: bool, summary: str)
    """
    zone_x, zone_y = zone

    # ── Step 0: 预处理——zone内死子当空点 ──
    alive_empty = [[False] * bs for _ in range(bs)]
    q = deque()
    for y in range(bs):
        for x in range(bs):
            if board[y][x] == "" and (x not in zone_x or y not in zone_y):
                alive_empty[y][x] = True
                q.append((x, y))
    while q:
        cx, cy = q.popleft()
        for nx, ny in [(cx-1,cy),(cx+1,cy),(cx,cy-1),(cx,cy+1)]:
            if 0 <= nx < bs and 0 <= ny < bs:
                if not alive_empty[ny][nx] and board[ny][nx] == "":
                    alive_empty[ny][nx] = True
                    q.append((nx, ny))

    # zone内的对手棋子：无外部气 → 死棋 → 当空点
    dead_opp = set()
    for y in range(bs):
        if y not in zone_y:
            continue
        for x in range(bs):
            if x not in zone_x:
                continue
            if board[y][x] != oc:
                continue
            has_breath = False
            for nx, ny in [(x-1,y),(x+1,y),(x,y-1),(x,y+1)]:
                if 0 <= nx < bs and 0 <= ny < bs:
                    if alive_empty[ny][nx]:
                        has_breath = True
                        break
            if not has_breath:
                dead_opp.add((x, y))

    cleaned_board = [row[:] for row in board]
    for x, y in dead_opp:
        cleaned_board[y][x] = ""

    # ── Step 1: 找玩家所有链（连通块）──
    visited = [[False] * bs for _ in range(bs)]
    chains = []
    chain_of = {}

    for y in range(bs):
        for x in range(bs):
            if cleaned_board[y][x] != pc or visited[y][x]:
                continue
            chain = []
            stack = [(x, y)]
            visited[y][x] = True
            while stack:
                cx, cy = stack.pop()
                chain.append((cx, cy))
                chain_of[(cx, cy)] = len(chains)
                for nx, ny in [(cx-1,cy),(cx+1,cy),(cx,cy-1),(cx,cy+1)]:
                    if 0 <= nx < bs and 0 <= ny < bs:
                        if not visited[ny][nx] and cleaned_board[ny][nx] == pc:
                            visited[ny][nx] = True
                            stack.append((nx, ny))
            chains.append(set(chain))

    if not chains:
        return False, "没有玩家棋子"

    # ── Step 2: 找围区 ──
    visited_empty = [[False] * bs for _ in range(bs)]
    regions = []

    for y in range(bs):
        for x in range(bs):
            if cleaned_board[y][x] != "" or visited_empty[y][x]:
                continue
            if x not in zone_x or y not in zone_y:
                continue
            region_pts = []
            border_chains = set()
            has_opponent = False
            stack = [(x, y)]
            visited_empty[y][x] = True
            while stack:
                cx, cy = stack.pop()
                region_pts.append((cx, cy))
                for nx, ny in [(cx-1,cy),(cx+1,cy),(cx,cy-1),(cx,cy+1)]:
                    if 0 <= nx < bs and 0 <= ny < bs:
                        if cleaned_board[ny][nx] == pc:
                            if (nx, ny) in chain_of:
                                border_chains.add(chain_of[(nx, ny)])
                        elif cleaned_board[ny][nx] == oc:
                            has_opponent = True
                        elif cleaned_board[ny][nx] == "" and not visited_empty[ny][nx]:
                            if nx in zone_x and ny in zone_y:
                                visited_empty[ny][nx] = True
                                stack.append((nx, ny))

            if not has_opponent and border_chains:
                regions.append((set(region_pts), border_chains))

    # ── Step 3: 检查每条链的关键围区 ──
    vital_count = {}
    for ci in range(len(chains)):
        vital_count[ci] = 0

    for region_pts, border_chains in regions:
        for ci in border_chains:
            chain_pts = chains[ci]
            all_adjacent = True
            for rx, ry in region_pts:
                is_adj = False
                for nx, ny in [(rx-1,ry),(rx+1,ry),(rx,ry-1),(rx,ry+1)]:
                    if (nx, ny) in chain_pts:
                        is_adj = True
                        break
                if not is_adj:
                    all_adjacent = False
                    break
            if all_adjacent:
                vital_count[ci] += 1

    # ── Step 4: 任何一条链有≥2个关键围区 → 活棋 ──
    for ci, cnt in vital_count.items():
        if cnt >= 2:
            return True, f"活棋！局部已做出{cnt}只真眼"

    # ── Step 5: 双活检测 ──
    for ci in range(len(chains)):
        chain_pts = chains[ci]
        inner_libs = set()
        for cx, cy in chain_pts:
            for nx, ny in [(cx-1,cy),(cx+1,cy),(cx,cy-1),(cx,cy+1)]:
                if 0 <= nx < bs and 0 <= ny < bs:
                    if board[ny][nx] == "" and not alive_empty[ny][nx]:
                        inner_libs.add((nx, ny))

        if len(inner_libs) < 2:
            continue

        mutual_count = 0
        for lx, ly in inner_libs:
            sim_p = [row[:] for row in board]
            sim_p[ly][lx] = pc
            _capture_after_move(sim_p, lx, ly, pc, bs)
            player_suicide = (sim_p[ly][lx] != pc)

            sim_o = [row[:] for row in board]
            sim_o[ly][lx] = oc
            _capture_after_move(sim_o, lx, ly, oc, bs)
            opp_suicide = (sim_o[ly][lx] != oc)

            if player_suicide and opp_suicide:
                mutual_count += 1

        if mutual_count >= 2:
            return True, f"双活！与对手在{mutual_count}口气处互不相让"

    # Step 4 已经处理了单链2眼的活棋，Step 5 处理了双活。
    # 走到这里说明：要么没有围区，要么有围区但分布在不同链上（各1眼 = 死棋）。
    # 围棋规则：只有同一连通块有2眼才活，跨链算眼是错的。
    total_vital = sum(vital_count.values())
    if total_vital == 0:
        return False, "没有真眼，还没活"
    else:
        # 有眼但不在一体：告诉玩家具体分布情况
        details = []
        for ci, cnt in vital_count.items():
            if cnt > 0:
                chain_size = len(chains[ci])
                details.append(f"链{ci}({chain_size}子)有{cnt}眼")
        return False, f"没活！" + "，".join(details) + "——眼不在同一块棋上"


# ── 死活题管理器 ──────────────────────────────────────────
class GoProblemManager:
    """管理死活题的获取、验证和完成
    玩家随意落子，KataGo实时应对并判定死活结果"""

    def __init__(self):
        self._sessions: dict[str, dict] = {}

    def get_problems(self) -> list:
        return [{
            "id": p["id"],
            "name": p["name"],
            "difficulty": p["difficulty"],
            "description": p["description"],
            "board_size": p["board_size"],
        } for p in TSUMEGO_PROBLEMS]

    def get_problem(self, problem_id: str) -> Optional[dict]:
        for p in TSUMEGO_PROBLEMS:
            if p["id"] == problem_id:
                return p
        return None

    def start_session(self, quest_id: str, problem_id: str) -> Optional[dict]:
        """开始一个死活题会话"""
        problem = self.get_problem(problem_id)
        if not problem:
            return None
        board = self._build_board(problem["board_size"], problem["initial"])

        # 计算固定杀棋区域（基于初始玩家的棋子，始终不变）
        size = problem["board_size"]
        player_stones = problem["initial"].get("B", [])
        # 题目坐标 (row=0=bottom) → board坐标 (row=0=top)
        board_stones = [(col, size - 1 - row) for col, row in player_stones]
        xs = [s[0] for s in board_stones]
        ys = [s[1] for s in board_stones]
        initial_x_range = range(max(0, min(xs)-2), min(size, max(xs)+3))
        initial_y_range = range(max(0, min(ys)-2), min(size, max(ys)+3))

        # 加载预计算正解序列
        pseq, oseq = get_pregen(problem_id)

        self._sessions[quest_id] = {
            "problem_id": problem_id,
            "board": board,
            "solved": False,
            "board_size": size,
            "player_color": "B",
            "opp_color": "W",
            "moves": 0,
            "ko_point": None,
            "initial_zone": (initial_x_range, initial_y_range),
            # 预计算序列追踪：preg_idx=-1 表示已偏离预计算序列，停用pregen
            "preg_moves": pseq if pseq else [],
            "preg_opp": oseq if oseq else [],
            "preg_idx": 0 if (pseq and oseq) else -1,
        }
        return {
            "board": board,
            "board_size": problem["board_size"],
            "description": problem["description"],
            "hint": problem["hint"],
        }

    def get_session_status(self, quest_id: str) -> Optional[dict]:
        """获取当前会话状态（供前端刷新后恢复）"""
        s = self._sessions.get(quest_id)
        if not s:
            return None
        return {
            "board": s["board"],
            "board_size": s["board_size"],
            "solved": s["solved"],
            "moves": s["moves"],
            "problem_id": s["problem_id"],
        }

    def _stones(self, session: dict) -> tuple:
        """从棋盘提取黑白棋子列表"""
        sb, sw = [], []
        size = session["board_size"]
        for y in range(size):
            for x in range(size):
                c = session["board"][y][x]
                if c == "B":
                    sb.append((x, y))
                elif c == "W":
                    sw.append((x, y))
        return sb, sw

    def _check_alive_by_katago(self, session: dict) -> tuple:
        """Benson算法判定死活（委托给独立函数）"""
        zone = session.get("initial_zone")
        if not zone:
            return False, "会话异常"
        return _benson_check(
            session["board"], session["player_color"], session["opp_color"],
            zone, session["board_size"]
        )

    def make_move(self, quest_id: str, col: int, row: int) -> dict:
        """玩家落子后用genmove自然应对，Benson算法判定死活"""
        session = self._sessions.get(quest_id)
        if not session:
            return {"error": "会话不存在"}
        if session["solved"]:
            return {"error": "已解决"}
        if session["board"][row][col]:
            return {"error": "该位置已有棋子"}

        bs = session["board_size"]
        pc = session["player_color"]
        oc = session["opp_color"]

        # 检查劫限制
        prev_ko = session.get("ko_point")
        if prev_ko and (col, row) == prev_ko:
            return {"error": f"劫争：不能马上提回{_gtp_str(col, row, bs)}，请下别处"}

        # 1. 玩家落子
        session["board"][row][col] = pc
        captured, ko_point = _capture_after_move(session["board"], col, row, pc, bs)
        session["ko_point"] = ko_point
        sb, sw = self._stones(session)

        zone = session.get("initial_zone")
        if not zone:
            return {"error": "会话异常：未找到initial_zone"}

        player_stones = list(sb if pc == "B" else sw)
        if not player_stones:
            session["moves"] += 1
            return {"error": "玩家棋子已被全提"}

        # 2. 玩家落子后Benson判定死活
        alive_now, summary_now = self._check_alive_by_katago(session)
        if alive_now:
            session["solved"] = True
            session["moves"] += 1
            return {"correct": True, "solved": True, "board": session["board"],
                    "opponent_move": "", "eyes": 0, "winrate": 0.9,
                    "summary": f"{summary_now}"}

        # 3. 对手应手：优先用预计算序列，偏离则fallback genmove
        pid = session.get("problem_id")
        preg_idx = session.get("preg_idx", -1)
        pseq = session.get("preg_moves", [])
        oseq = session.get("preg_opp", [])

        # 检查玩家走法是否匹配预计算序列
        player_gtp = _gtp_str(col, row, bs)
        if preg_idx >= 0 and preg_idx < len(pseq):
            if player_gtp == pseq[preg_idx]:
                # 匹配：用预计算对手应手
                if preg_idx < len(oseq):
                    opponent_move = oseq[preg_idx]
                else:
                    opponent_move = ""
                session["preg_idx"] = preg_idx + 1
            else:
                # 偏离：停用pregen，fallback到genmove
                session["preg_idx"] = -1
                opponent_move = _engine.genmove(oc, bs, sb, sw)
        else:
            opponent_move = _engine.genmove(oc, bs, sb, sw)
        opp_coord = ""
        if opponent_move:
            try:
                ox, oy = parse_gtp(opponent_move, bs)
                if session["board"][oy][ox] == "":
                    session["ko_point"] = None
                    session["board"][oy][ox] = oc
                    opp_captured, opp_ko = _capture_after_move(
                        session["board"], ox, oy, oc, bs)
                    if opp_ko:
                        session["ko_point"] = opp_ko
                    opp_coord = opponent_move
            except (ValueError, IndexError):
                pass

        session["moves"] += 1

        # 5. 对手落子后再次Benson判定
        alive_final, summary_final = self._check_alive_by_katago(session)
        session["solved"] = alive_final

        if alive_final:
            return {"correct": True, "solved": True, "board": session["board"],
                    "opponent_move": opp_coord, "eyes": 0, "winrate": 0.9,
                    "summary": f"{summary_final}"}
        else:
            return {"correct": True, "solved": False, "board": session["board"],
                    "opponent_move": opp_coord, "eyes": 0, "winrate": 0.5,
                    "summary": f"对手应{opp_coord}，{summary_final}"}

    def evaluate(self, quest_id: str) -> dict:
        """用Benson算法判定死活（与make_move保持一致）"""
        session = self._sessions.get(quest_id)
        if not session:
            return {"error": "会话不存在"}
        alive, summary = self._check_alive_by_katago(session)
        return {"alive": alive, "winrate": 0.9 if alive else 0.3,
                "eyes": 2 if alive else 0,
                "message": summary}

    def get_session(self, quest_id: str) -> Optional[dict]:
        return self._sessions.get(quest_id)

    def _build_board(self, size: int, initial: dict) -> list:
        """构建初始棋盘 (list[list[str]])
        题目坐标: row=0=bottom, 但 board[row][col] 中 row=0=top
        所以需要翻转: board_row = size - 1 - row
        """
        board = [["" for _ in range(size)] for _ in range(size)]
        for color, stones in initial.items():
            for col, row in stones:
                board_row = size - 1 - row
                board[board_row][col] = color
        return board


# ── 独立分析工具接口 ───────────────────────────────────
def analyze_position(stones_b: list, stones_w: list,
                     board_size: int = 19, color: str = "B",
                     moves_count: int = 5) -> list:
    """分析任意棋盘位置，返回推荐走法列表"""
    return _engine.analyze(color, board_size, stones_b, stones_w, moves_count)


def auto_solve(stones_b: list, stones_w: list,
               board_size: int = 9, player_color: str = "B",
               max_moves: int = 50, problem_id: str = None,
               force_genmove: bool = False) -> dict:
    """自动求解死活题：优先使用预计算正解序列，否则fallback到genmove
    force_genmove=True 时跳过预计算，强制只用 genmove（用于对比测试）
    输入 stones_b/stones_w: [(col, flipped_row), ...] 前端格式 flipped_row = size-1-frontRow
    内部统一用 (col, row_from_top) row_from_top=0=top
    返回 board: list[list[str]] 前端格式 board[frontRow][col]
    """
    import time
    start_time = time.time()
    # 前端坐标 (col, flippedRow) → 内部 (col, row_from_top)
    def _to_internal(stones, size):
        return [(x, size - 1 - y) for x, y in stones]

    stones_b = _to_internal(stones_b, board_size)
    stones_w = _to_internal(stones_w, board_size)

    # 构建初始棋盘（内部坐标）
    board = [["" for _ in range(board_size)] for _ in range(board_size)]
    for x, y in stones_b:
        board[y][x] = "B"
    for x, y in stones_w:
        board[y][x] = "W"

    pc = player_color
    oc = "W" if pc == "B" else "B"

    # 动态zone
    def _calc_zone(board, pc_color):
        xs, ys = [], []
        for y in range(board_size):
            for x in range(board_size):
                if board[y][x] == pc_color:
                    xs.append(x); ys.append(y)
        if not xs:
            return (range(0,0), range(0,0))
        return (range(max(0,min(xs)-2), min(board_size,max(xs)+3)),
                range(max(0,min(ys)-2), min(board_size,max(ys)+3)))

    # 获取预计算序列（force_genmove 时跳过）
    pseq, oseq = (None, None) if force_genmove else (get_pregen(problem_id) if problem_id else (None, None))
    has_pregen = pseq is not None and oseq is not None
    p_idx = 0  # 玩家走法索引
    o_idx = 0  # 对手走法索引

    moves = []

    def _place_move(board, gtp_coord: str, color: str, board_size: int):
        """在棋盘上落子（GTP坐标），返回是否成功"""
        try:
            col, row = parse_gtp(gtp_coord, board_size)
        except (ValueError, IndexError):
            return False
        if board[row][col] != "":
            return False
        board[row][col] = color
        captured, _ = _capture_after_move(board, col, row, color, board_size)
        moves.append({"step": len(moves) + 1, "color": color,
                      "coord": gtp_coord, "captures": len(captured)})
        return True

    for step in range(max_moves):
        sb, sw = _stones_from_board(board, board_size)
        zone = _calc_zone(board, pc)

        alive, summary = _benson_check(board, pc, oc, zone, board_size)
        if alive:
            result_board = [board[board_size - 1 - r] for r in range(board_size)]
            return {"solved": True, "result": "alive", "summary": summary,
                    "moves": moves, "board": result_board,
                    "elapsed_sec": round(time.time() - start_time, 2)}

        # ── 玩家走棋（pregen优先，fallback genmove） ──
        if has_pregen and p_idx < len(pseq):
            player_move = pseq[p_idx]
            p_idx += 1
        else:
            player_move = _engine.genmove(pc, board_size, sb, sw)

        if not player_move:
            alive2, summary2 = _benson_check(board, pc, oc, zone, board_size)
            result_board = [board[board_size - 1 - r] for r in range(board_size)]
            return {"solved": alive2, "result": "alive" if alive2 else "dead",
                    "summary": summary2 + "（无棋可走）",
                    "moves": moves, "board": result_board,
                    "elapsed_sec": round(time.time() - start_time, 2)}

        if not _place_move(board, player_move, pc, board_size):
            continue

        alive, summary = _benson_check(board, pc, oc, zone, board_size)
        if alive:
            result_board = [board[board_size - 1 - r] for r in range(board_size)]
            return {"solved": True, "result": "alive", "summary": summary,
                    "moves": moves, "board": result_board,
                    "elapsed_sec": round(time.time() - start_time, 2)}

        # ── 对手走棋（pregen优先，fallback genmove） ──
        sb, sw = _stones_from_board(board, board_size)
        if has_pregen and o_idx < len(oseq):
            opp_move = oseq[o_idx]
            o_idx += 1
        else:
            opp_move = _engine.genmove(oc, board_size, sb, sw)

        if opp_move:
            _place_move(board, opp_move, oc, board_size)

        alive, summary = _benson_check(board, pc, oc, zone, board_size)
        if alive:
            result_board = [board[board_size - 1 - r] for r in range(board_size)]
            return {"solved": True, "result": "alive", "summary": summary,
                    "moves": moves, "board": result_board,
                    "elapsed_sec": round(time.time() - start_time, 2)}

    # 达到最大步数
    alive, summary = _benson_check(board, pc, oc, zone, board_size)
    result_board = [board[board_size - 1 - r] for r in range(board_size)]
    return {"solved": alive, "result": "alive" if alive else "dead",
            "summary": f"{summary}（已达{max_moves}步上限）",
            "moves": moves, "board": result_board,
            "elapsed_sec": round(time.time() - start_time, 2)}
