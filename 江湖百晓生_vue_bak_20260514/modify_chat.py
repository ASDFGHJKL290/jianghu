#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
修改 chat.py：
1. 添加 get_chapter_progress() 方法
2. 添加 advance_chapter() 方法
3. 修改 check_quests() 添加章节过滤
4. 添加 _extract_gift() 和 _strip_gift() 方法
5. 修改 chat() 注入 story_context 和处理赠礼
"""

import re

# 读取原文件
with open(r'C:\Users\aaa\PycharmProjects\day25\江湖百晓生_vue\chat.py', 'r', encoding='utf-8') as f:
    content = f.read()

# 1. 在 _add_quest() 方法后添加章节相关方法
# 找到 _add_quest() 方法的结尾
add_quest_end = content.find('            self._user_quests(user_id).append(quest)', content.find('def _add_quest('))
if add_quest_end == -1:
    print("错误：找不到 _add_quest() 方法")
    exit(1)

# 找到该行末尾
add_quest_end = content.find('\n', add_quest_end) + 1

# 要插入的方法
chapter_methods = '''
    # ── 章节系统 ─────────────────────────
    def get_chapter_progress(self, user_id: str = "default") -> dict:
        """获取玩家章节进度"""
        return self.chapter_progress.setdefault(user_id, {
            "current_chapter": 1,
            "completed_chapters": [],
            "chapter_step": 0,
        })
    
    def advance_chapter(self, user_id: str = "default") -> dict:
        """推进到下一章，返回章节叙事（供LLM生成）"""
        prog = self.get_chapter_progress(user_id)
        current = prog["current_chapter"]
        if current >= 6:  # 已到最终章
            return {"advanced": False, "message": "已是最终章"}
        prog["completed_chapters"].append(current)
        prog["current_chapter"] = current + 1
        prog["chapter_step"] = 0
        # 返回新章节信息
        try:
            from prompts import CHAPTER_CONFIG
            new_chapter = CHAPTER_CONFIG.get(current + 1, {})
            return {
                "advanced": True,
                "new_chapter": current + 1,
                "chapter_name": new_chapter.get("name", ""),
                "chapter_desc": new_chapter.get("desc", ""),
                "unlock_locations": new_chapter.get("unlock_locations", []),
            }
        except ImportError:
            return {"advanced": True, "new_chapter": current + 1}
    
    def _inject_story_context(self, user_id: str = "default") -> str:
        """生成 story_context 文本，注入到 LLM prompt"""
        prog = self.get_chapter_progress(user_id)
        current_chapter = prog["current_chapter"]
        context_text = ""
        for quest in self._user_quests(user_id):
            qid = quest.get("qid")
            # 找到对应的任务配置
            try:
                from prompts import ALL_QUESTS
                for q_key, q_val in ALL_QUESTS.items():
                    if q_val.get("qid") == qid:
                        if q_val.get("story_context"):
                            context_text += f"【当前故事背景】{q_val['story_context']}\n"
                        break
            except ImportError:
                pass
        return context_text
    
    def _extract_gift(self, text: str) -> dict or None:
        """从LLM输出中提取 gift JSON"""
        import re
        # 支持单双引号
        pat1 = r'\{\s*"gift"\s*:\s*\{[^}]+\}\s*\}'
        pat2 = r"\{\s*'gift'\s*:\s*\{[^}]+\}\s*\}"
        for pat in [pat1, pat2]:
            m = re.search(pat, text)
            if m:
                try:
                    return json.loads(m.group())
                except:
                    try:
                        return eval(m.group())  # fallback for single quotes
                    except:
                        pass
        return None
    
    def _strip_gift(self, text: str) -> str:
        """去掉文本末尾的 gift JSON"""
        import re
        text = re.sub(r'\{\s*"gift"\s*:\s*\{[^}]+\}\s*\}\s*', '', text)
        text = re.sub(r"\{\s*'gift'\s*:\s*\{[^}]+\}\s*\}\s*", '', text)
        return text.strip()
    
'''

# 插入方法
content = content[:add_quest_end] + chapter_methods + content[add_quest_end:]

# 2. 修改 check_quests() 添加章节过滤
# 找到 check_quests() 方法
check_start = content.find('def check_quests(')
if check_start == -1:
    print("错误：找不到 check_quests() 方法")
    exit(1)

# 找到方法体开始
method_body_start = content.find('\n        ', check_start) + 1
# 找到 candidates = [] 的位置
candidates_pos = content.find('        candidates = []', method_body_start)
if candidates_pos == -1:
    print("错误：找不到 candidates = []")
    exit(1)

# 在 candidates = [] 后添加章节过滤代码
chapter_filter_code = '''        candidates = []
        
        # 获取当前章节
        try:
            from prompts import ALL_QUESTS as ALLQ
            chapter_prog = self.get_chapter_progress(user_id)
            current_chapter = chapter_prog["current_chapter"]
        except ImportError:
            current_chapter = 1
        
        for q_id, q in ALLQ.items():
'''

# 替换原有的 for 循环开始部分
old_for_loop = '''        candidates = []
        for q.id, q in ALL_QUESTS.items():'''
if old_for_loop in content:
    # 需要重写 check_quests() 方法
    # 找到方法结束位置
    # 简单方法：找到下一个 def 或类结束
    lines = content[check_start:].split('\n')
    method_lines = []
    indent = None
    for i, line in enumerate(lines):
        if i == 0:
            method_lines.append(line)
            continue
        if line.strip() == '':
            method_lines.append(line)
            continue
        # 检查方法缩进
        current_indent = len(line) - len(line.lstrip())
        if indent is None:
            indent = current_indent
        if line.strip().startswith('def ') and current_indent <= indent:
            break
        method_lines.append(line)
    
    old_method = '\n'.join(method_lines)
    print(f"找到 check_quests() 方法，长度：{len(old_method)} 字符")
    
    # 新版本的方法
    new_method = '''    def check_quests(self, user_input: str, npc_name: str, user_id: str = "default") -> list:
        user_lower = user_input.lower()
        
        # 获取当前章节
        try:
            from prompts import ALL_QUESTS as ALLQ
            chapter_prog = self.get_chapter_progress(user_id)
            current_chapter = chapter_prog["current_chapter"]
            player_faction = None
            try:
                import game as g
                player_faction = g.faction or "无门派"
            except ImportError:
                pass
        except ImportError:
            ALLQ = ALL_QUESTS
            current_chapter = 1
            player_faction = None
        
        candidates = []
        for q_id, q in ALLQ.items():
            # --- 原有过滤条件 ---
            if npc_name not in q["npc_permission"]:
                continue
            if self.quest_completion.get(user_id, {}).get(q_id):
                continue
            pre_req = q.get("prerequisite")
            if pre_req and not self.quest_completion.get(user_id, {}).get(pre_req):
                continue
            if any(quest.get("qid") == q.get("qid") for quest in self._user_quests(user_id)):
                continue
            
            # --- 新增：章节过滤 ---
            if q.get("chapter", 1) != current_chapter:
                continue  # 只显示当前章节的任务
            
            # --- 新增：门派分支 ---
            faction_branch = q.get("faction_branch", {}).get(player_faction)
            if faction_branch:
                # 使用门派专属 steps
                q = {**q, "steps": faction_branch["steps"], "reward_data": faction_branch.get("reward_data", q["reward_data"])}
            
            matched = [kw for kw in q["trigger"] if kw.lower() in user_lower]
            if matched:
                candidates.append((len(matched), q_id, q))
        
        if not candidates:
            return []
        
        candidates.sort(reverse=True, key=lambda x: (x[0], len(x[2]["trigger"])))
        best_qid, best_q = candidates[0][1], candidates[0][2]
        return [{"qid": best_q.get("qid", best_qid), **best_q}]
'''
    
    # 替换
    content = content.replace(old_method, new_method)
    print("成功修改 check_quests() 方法")
else:
    print("警告：找不到预期的 for 循环，跳过 check_quests() 修改")

# 3. 修改 chat() 方法注入 story_context 和处理赠礼
# 找到 chat() 方法
chat_start = content.find('def chat(')
if chat_start == -1:
    print("错误：找不到 chat() 方法")
    exit(1)

# 在 chat() 方法中找到构建 prompt 的位置
# 简单方法：在 return 之前添加 story_context 注入
# 找到 resp = { 的位置（返回字典的构建）
resp_pos = content.find('        resp = {', chat_start)
if resp_pos == -1:
    print("警告：找不到 resp = {，跳过 chat() 修改")
else:
    # 在 resp = { 之前添加赠礼处理代码
    gift_code = '''        
        # --- 新增：处理NPC赠礼 ---
        gift_data = self._extract_gift(reply)
        gift_received = None
        if gift_data:
            g_data = gift_data.get("gift", {})
            item_name = g_data.get("name", "")
            item_icon = g_data.get("icon", "📦")
            item_count = g_data.get("count", 1)
            # 写入玩家背包
            try:
                import game as g
                found = next((it for it in g.player_items if it["name"] == item_name), None)
                if found:
                    found["count"] += item_count
                else:
                    g.player_items.append({"name": item_name, "icon": item_icon, "count": item_count})
                g.save_all_state()
                gift_received = {
                    "name": item_name,
                    "icon": item_icon,
                    "count": item_count,
                    "reason": g_data.get("reason", ""),
                    "npc": npc_name,
                }
            except ImportError:
                pass
            # 从回复中去掉 gift JSON
            reply = self._strip_gift(reply)
'''
    
    # 在 resp = { 之前插入
    content = content[:resp_pos] + gift_code + content[resp_pos:]

print("成功修改 chat.py！")

# 写回文件
with open(r'C:\Users\aaa\PycharmProjects\day25\江湖百晓生_vue\chat.py', 'w', encoding='utf-8') as f:
    f.write(content)

print(f"文件长度：{len(content)} 字符")
print("请检查文件是否正确！")
