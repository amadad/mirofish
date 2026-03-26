"""Per-simulation LLM cost tracking."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict


@dataclass
class ProviderStats:
    calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    input_price_per_1m: float = 0.0
    output_price_per_1m: float = 0.0

    @property
    def estimated_cost(self) -> float:
        return (
            self.input_tokens * self.input_price_per_1m / 1_000_000
            + self.output_tokens * self.output_price_per_1m / 1_000_000
        )


class CostTracker:
    """Track LLM usage and cost across providers for a single simulation."""

    def __init__(self):
        self._providers: Dict[str, ProviderStats] = {}

    def set_pricing(self, provider: str, input_per_1m: float, output_per_1m: float) -> None:
        stats = self._providers.setdefault(provider, ProviderStats())
        stats.input_price_per_1m = input_per_1m
        stats.output_price_per_1m = output_per_1m

    def record(
        self,
        provider: str,
        model: str,
        input_tokens: int = 0,
        output_tokens: int = 0,
    ) -> None:
        stats = self._providers.setdefault(provider, ProviderStats())
        stats.calls += 1
        stats.input_tokens += input_tokens
        stats.output_tokens += output_tokens

    def summary(self) -> dict:
        providers = {}
        total_cost = 0.0
        total_calls = 0
        for name, stats in self._providers.items():
            cost = stats.estimated_cost
            total_cost += cost
            total_calls += stats.calls
            providers[name] = {
                "calls": stats.calls,
                "input_tokens": stats.input_tokens,
                "output_tokens": stats.output_tokens,
                "estimated_cost": round(cost, 4),
            }
        return {
            "total_calls": total_calls,
            "total_estimated_cost": round(total_cost, 4),
            "providers": providers,
        }
