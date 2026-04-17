"""
公共知识库模块（V6 热加载版）

V5：消除重复 _load_kb
V6：支持知识库热加载，修改 KB 文件后无需重启服务
"""
from __future__ import annotations

import os
import time
import threading
from pathlib import Path

_KB_DIR = Path(__file__).parent.parent / "knowledge_base"

# ── 文件修改时间追踪（用于热加载）─────────────────────────────────────────────
_file_mtimes: dict[str, float] = {}
_kb_cache: dict[str, str] = {}
_cache_lock = threading.Lock()


def _load_kb(name: str) -> str:
    """从 knowledge_base 目录加载文件内容，支持缓存"""
    with _cache_lock:
        p = _KB_DIR / name
        try:
            mtime = p.stat().st_mtime
        except FileNotFoundError:
            _kb_cache[name] = ""
            return ""

        # 检查是否需要重新加载
        cached_mtime = _file_mtimes.get(name, 0)
        if name in _kb_cache and mtime <= cached_mtime:
            return _kb_cache[name]

        # 重新加载
        try:
            content = p.read_text(encoding="utf-8")
            _kb_cache[name] = content
            _file_mtimes[name] = mtime
            return content
        except Exception:
            return _kb_cache.get(name, "")


def reload_kb(name: str) -> str:
    """强制重新加载指定知识库文件"""
    with _cache_lock:
        _file_mtimes.pop(name, None)
        _kb_cache.pop(name, None)
    return _load_kb(name)


def reload_all_kb() -> dict[str, bool]:
    """强制重新加载所有知识库文件，返回各文件加载状态"""
    results = {}
    for name in _KB_FILE_REGISTRY:
        old = _kb_cache.get(name, "")
        new = reload_kb(name)
        results[name] = (old != new)
    return results


def check_kb_updates() -> list[str]:
    """检查哪些 KB 文件有更新（不重新加载，仅检测）"""
    updated = []
    for name in _KB_FILE_REGISTRY:
        p = _KB_DIR / name
        try:
            mtime = p.stat().st_mtime
        except FileNotFoundError:
            continue
        if mtime > _file_mtimes.get(name, 0):
            updated.append(name)
    return updated


# ═══════════════════════════════════════════════════════════════════════════════
# 知识库文件注册表
# ═══════════════════════════════════════════════════════════════════════════════

_KB_FILE_REGISTRY: list[str] = [
    # 原有 Agent
    "anti_ai_rules.md",
    "before_after_examples.md",
    "writing_techniques.md",
    "rules/common-mistakes.md",
    "references/writing-techniques/five-senses-description.md",
    "references/writing-techniques/show-dont-tell.md",
    "agent-specific/writer-skills.md",
    "agent-specific/reviewer-checklist.md",
    "rules/review-criteria-95.md",
    "rules/redlines.md",
    # V4 增强 Agent
    "agent-specific/hook-designer-guide.md",
    "agent-specific/opening-ending-guide.md",
    "agent-specific/emotion-curve-guide.md",
    "agent-specific/dialogue-expert-guide.md",
    "agent-specific/character-growth-guide.md",
    "agent-specific/style-consistency-guide.md",
    "agent-specific/scene-architect-guide.md",
    "agent-specific/psychological-portrayal-guide.md",
]

# ═══════════════════════════════════════════════════════════════════════════════
# 知识库预加载 — 通过属性访问触发懒加载
# ═══════════════════════════════════════════════════════════════════════════════

# 原有 Agent
def _kb_anti_ai() -> str: return _load_kb("anti_ai_rules.md")
def _kb_before_after() -> str: return _load_kb("before_after_examples.md")
def _kb_writing_techniques() -> str: return _load_kb("writing_techniques.md")
def _kb_common_mistakes() -> str: return _load_kb("rules/common-mistakes.md")
def _kb_five_senses() -> str: return _load_kb("references/writing-techniques/five-senses-description.md")
def _kb_show_dont_tell() -> str: return _load_kb("references/writing-techniques/show-dont-tell.md")
def _kb_writer_skills() -> str: return _load_kb("agent-specific/writer-skills.md")
def _kb_reviewer_checklist() -> str: return _load_kb("agent-specific/reviewer-checklist.md")
def _kb_review_criteria_95() -> str: return _load_kb("rules/review-criteria-95.md")
def _kb_redlines() -> str: return _load_kb("rules/redlines.md")

# V4 增强 Agent
def _kb_hook_designer() -> str: return _load_kb("agent-specific/hook-designer-guide.md")
def _kb_opening_ending() -> str: return _load_kb("agent-specific/opening-ending-guide.md")
def _kb_emotion_curve() -> str: return _load_kb("agent-specific/emotion-curve-guide.md")
def _kb_dialogue() -> str: return _load_kb("agent-specific/dialogue-expert-guide.md")
def _kb_char_growth() -> str: return _load_kb("agent-specific/character-growth-guide.md")
def _kb_style_consistency() -> str: return _load_kb("agent-specific/style-consistency-guide.md")
def _kb_scene_architect() -> str: return _load_kb("agent-specific/scene-architect-guide.md")
def _kb_psychological() -> str: return _load_kb("agent-specific/psychological-portrayal-guide.md")


class _LazyKB:
    """懒加载代理：访问时才读取文件，且自动检测更新"""
    def __init__(self, loader):
        self._loader = loader
    def __str__(self): return self._loader()
    def __repr__(self): return f"<LazyKB:{self._loader.__name__}>"
    # 支持字符串操作
    def __add__(self, other): return str(self) + other
    def __radd__(self, other): return other + str(self)
    def __len__(self): return len(str(self))
    def __bool__(self): return bool(str(self))
    def __contains__(self, item): return item in str(self)
    def __iter__(self): return iter(str(self))


# 模块级变量 — 使用懒加载代理
KB_ANTI_AI = _LazyKB(_kb_anti_ai)
KB_BEFORE_AFTER = _LazyKB(_kb_before_after)
KB_WRITING_TECHNIQUES = _LazyKB(_kb_writing_techniques)
KB_COMMON_MISTAKES = _LazyKB(_kb_common_mistakes)
KB_FIVE_SENSES = _LazyKB(_kb_five_senses)
KB_SHOW_DONT_TELL = _LazyKB(_kb_show_dont_tell)
KB_WRITER_SKILLS = _LazyKB(_kb_writer_skills)
KB_REVIEWER_CHECKLIST = _LazyKB(_kb_reviewer_checklist)
KB_REVIEW_CRITERIA_95 = _LazyKB(_kb_review_criteria_95)
KB_REDLINES = _LazyKB(_kb_redlines)

KB_HOOK_DESIGNER = _LazyKB(_kb_hook_designer)
KB_OPENING_ENDING = _LazyKB(_kb_opening_ending)
KB_EMOTION_CURVE = _LazyKB(_kb_emotion_curve)
KB_DIALOGUE = _LazyKB(_kb_dialogue)
KB_CHAR_GROWTH = _LazyKB(_kb_char_growth)
KB_STYLE_CONSISTENCY = _LazyKB(_kb_style_consistency)
KB_SCENE_ARCHITECT = _LazyKB(_kb_scene_architect)
KB_PSYCHOLOGICAL = _LazyKB(_kb_psychological)

# ═══════════════════════════════════════════════════════════════════════════════
# 知识库查询追踪
# ═══════════════════════════════════════════════════════════════════════════════

_KB_QUERIES: list[tuple[str, str, str]] = []  # (agent_role, file_name, context)


def track_kb_query(agent_role: str, file_name: str, context: str = ""):
    """记录一次知识库查询（供 KBIncentiveTracker 使用）"""
    _KB_QUERIES.append((agent_role, file_name, context))


def get_kb_queries() -> list[tuple[str, str, str]]:
    """获取并清空自上次调用以来的所有知识库查询记录"""
    queries = list(_KB_QUERIES)
    _KB_QUERIES.clear()
    return queries
