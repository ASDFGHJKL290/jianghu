# -*- coding: utf-8 -*-
"""
pregen.py — 江湖百晓生 离线预生成工具
单独运行，不与服务器绑定。生成的故事节点存到 state/events.db。
用法：python pregen.py [节点数=100]
"""
import sys, os

# 把项目根目录加入路径
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".env"))

from chat import JianghuChat
from event_engine import EventManager

def main():
    total = int(sys.argv[1]) if len(sys.argv) > 1 else 100
    print(f"[Pregen] 初始化引擎...")
    chat = JianghuChat()
    em = EventManager(chat)
    chat.event_manager = em
    # 生成一组节点，带组标签
    import random, string, time
    gid = f"g_{int(time.time())}"
    print(f"[Pregen] 开始预生成 {total} 个节点 (组={gid})...")
    em.generate_story_tree(total, group_id=gid)
    print(f"[Pregen] 完成，组={gid}（节点连接由运行时动态解析）")

if __name__ == "__main__":
    main()
