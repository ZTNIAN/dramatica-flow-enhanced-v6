"""
Token 使用追踪器（V6 新增）

记录每次 LLM 调用的 token 消耗，按 Agent/章节聚合，用于成本分析。
"""
from __future__ import annotations

import json
import time
from dataclasses import dataclass, field, asdict
from pathlib import Path


@dataclass
class TokenCall:
    """单次 LLM 调用记录"""
    agent: str          # Agent 名称（如 architect, writer, auditor）
    chapter: int        # 章节号（0 = 非章节相关）
    model: str          # 使用的模型
    input_tokens: int
    output_tokens: int
    timestamp: float = 0.0
    context: str = ""   # 简短描述（如 "plan_chapter", "audit"）

    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens


# 各模型的定价（美元/百万 token，2026参考价）
_MODEL_PRICING: dict[str, tuple[float, float]] = {
    # (input_price_per_1M, output_price_per_1M)
    "deepseek-chat": (0.14, 0.28),
    "deepseek-reasoner": (0.55, 2.19),
    "claude-sonnet-4-20250514": (3.0, 15.0),
    "claude-3-5-sonnet-20241022": (3.0, 15.0),
    "gpt-4o": (2.5, 10.0),
    "gpt-4o-mini": (0.15, 0.6),
    "gpt-4-turbo": (10.0, 30.0),
    "llama3.1": (0.0, 0.0),  # 本地模型免费
}


class TokenTracker:
    """Token 使用追踪器"""

    def __init__(self):
        self._calls: list[TokenCall] = []

    def record(
        self,
        agent: str,
        chapter: int,
        model: str,
        input_tokens: int,
        output_tokens: int,
        context: str = "",
    ):
        """记录一次 token 消耗"""
        self._calls.append(TokenCall(
            agent=agent,
            chapter=chapter,
            model=model,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            timestamp=time.time(),
            context=context,
        ))

    def get_chapter_usage(self, chapter: int) -> dict:
        """获取指定章节的 token 使用汇总"""
        chapter_calls = [c for c in self._calls if c.chapter == chapter]
        if not chapter_calls:
            return {"chapter": chapter, "total_tokens": 0, "calls": 0, "cost_usd": 0.0}

        total_input = sum(c.input_tokens for c in chapter_calls)
        total_output = sum(c.output_tokens for c in chapter_calls)
        cost = self._estimate_cost(chapter_calls)

        by_agent: dict[str, dict] = {}
        for c in chapter_calls:
            if c.agent not in by_agent:
                by_agent[c.agent] = {"input": 0, "output": 0, "calls": 0}
            by_agent[c.agent]["input"] += c.input_tokens
            by_agent[c.agent]["output"] += c.output_tokens
            by_agent[c.agent]["calls"] += 1

        return {
            "chapter": chapter,
            "total_input_tokens": total_input,
            "total_output_tokens": total_output,
            "total_tokens": total_input + total_output,
            "calls": len(chapter_calls),
            "cost_usd": round(cost, 4),
            "by_agent": by_agent,
        }

    def get_total_usage(self) -> dict:
        """获取总计 token 使用"""
        if not self._calls:
            return {"total_tokens": 0, "calls": 0, "cost_usd": 0.0}

        total_input = sum(c.input_tokens for c in self._calls)
        total_output = sum(c.output_tokens for c in self._calls)
        cost = self._estimate_cost(self._calls)

        by_chapter: dict[str, dict] = {}
        for c in self._calls:
            ch_key = str(c.chapter)
            if ch_key not in by_chapter:
                by_chapter[ch_key] = {"tokens": 0, "cost": 0.0}
            by_chapter[ch_key]["tokens"] += c.total_tokens

        by_agent: dict[str, int] = {}
        for c in self._calls:
            by_agent[c.agent] = by_agent.get(c.agent, 0) + c.total_tokens

        by_model: dict[str, int] = {}
        for c in self._calls:
            by_model[c.model] = by_model.get(c.model, 0) + c.total_tokens

        return {
            "total_input_tokens": total_input,
            "total_output_tokens": total_output,
            "total_tokens": total_input + total_output,
            "calls": len(self._calls),
            "cost_usd": round(cost, 4),
            "by_agent": by_agent,
            "by_model": by_model,
        }

    def save(self, path: Path, chapter: int = 0):
        """保存 token 使用记录到 JSON 文件"""
        existing = []
        if path.exists():
            try:
                existing = json.loads(path.read_text(encoding="utf-8"))
            except Exception:
                existing = []

        if chapter > 0:
            existing.append(self.get_chapter_usage(chapter))
        else:
            existing.append(self.get_total_usage())

        path.write_text(
            json.dumps(existing, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def _estimate_cost(self, calls: list[TokenCall]) -> float:
        """估算 token 费用（美元）"""
        total_cost = 0.0
        for c in calls:
            pricing = _MODEL_PRICING.get(c.model, (1.0, 3.0))  # 默认价格
            input_cost = (c.input_tokens / 1_000_000) * pricing[0]
            output_cost = (c.output_tokens / 1_000_000) * pricing[1]
            total_cost += input_cost + output_cost
        return total_cost

    def clear(self):
        """清空记录"""
        self._calls.clear()


# 全局单例
_global_tracker = TokenTracker()


def get_tracker() -> TokenTracker:
    """获取全局 token 追踪器"""
    return _global_tracker
