# -*- coding: utf-8 -*-
"""
utils.py — 江湖百晓生 v2.0 工具函数
安全校验 / 历史截断 / 数值工具 / 时间工具
"""
import re
import datetime


DANGEROUS_PATTERNS = [
    r"忘记.{0,5}指令", r"忽略.{0,5}规则", r"你现在.{0,5}是",
    r"system[:：]?", r"role[:：]?[\s]*system",
    r"你是[\s]*AI", r"你是[\s]*机器人",
    r"解锁.{0,5}权限", r"突破.{0,5}限制",
    r"显示.{0,5}提示词", r"泄露.{0,5}设定",
]


def sanitize_input(user_input: str) -> tuple[str, str]:
    """
    输入安全校验。
    返回 (status, clean_text)
    status: ok / empty / dangerous / gibberish
    """
    if not user_input or not user_input.strip():
        return "empty", ""
    text = user_input.strip()

    # 危险指令检测
    for pattern in DANGEROUS_PATTERNS:
        if re.search(pattern, text, re.IGNORECASE):
            return "dangerous", text

    # 乱码检测
    chinese_chars = re.findall(r'[\u4e00-\u9fff]', text)
    english_letters = re.findall(r'[A-Za-z]', text)
    digits = re.findall(r'\d', text)
    special_chars = re.findall(
        r'[^A-Za-z0-9\u4e00-\u9fff\s\u3000-\u303f\uff00-\uffef，。！？、；：""''（）【】《》.,!?;:"\'()\\]·—～…、]',
        text
    )
    total = len(text)
    cn = len(chinese_chars)
    en = len(english_letters)
    num = len(digits)
    junk = len(special_chars)

    common_keywords = ["华山", "少林", "武当", "丐帮", "峨眉", "江湖", "剑法", "武功",
                       "掌门", "论剑", "秘籍", "侠客", "武林", "门派", "天下",
                       "侠", "剑", "拳", "刀", "内功", "轻功", "气功", "掌法"]
    has_kw = lambda t: any(kw in t for kw in common_keywords)

    if junk >= 2 and junk / total > 0.25:
        return "gibberish", text
    if en > 0 and cn == 0 and not has_kw(text):
        return "gibberish", text
    if en > 0 and num > 0 and junk > 0 and cn == 0:
        return "gibberish", text
    if (num + junk) / total > 0.7 and cn == 0:
        return "gibberish", text

    return "ok", text


def truncate_history(history: list, max_turns: int = 10) -> list:
    """截断对话历史，保留最近 max_turns 轮"""
    if len(history) > max_turns * 2:
        return history[-max_turns * 2:]
    return history


def clamp(val, lo, hi):
    """数值限幅 [lo, hi]"""
    return max(lo, min(hi, val))


def now_iso() -> str:
    """当前时间的 ISO 格式字符串"""
    return datetime.datetime.now().isoformat()
