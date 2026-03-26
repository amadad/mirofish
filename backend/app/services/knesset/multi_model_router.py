"""AgentModelRouter — assigns different LLM models to different agent
importance tiers for cost-efficient Knesset simulation.

Primary MKs (PM, ministers, faction leaders) get higher-quality models,
while background MKs use cheaper/faster models with shorter outputs.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Dict, List, Optional

from .types import KnessetPersona

logger = logging.getLogger("mirofish.knesset.multi_model_router")


# ---------------------------------------------------------------------------
# Tier configuration
# ---------------------------------------------------------------------------

@dataclass
class AgentTier:
    """LLM configuration for an agent importance tier."""

    tier: str  # "primary" | "secondary" | "background"
    provider: str
    model: str
    max_tokens: int
    temperature: float


# ---------------------------------------------------------------------------
# AgentModelRouter
# ---------------------------------------------------------------------------

class AgentModelRouter:
    """Assigns different LLM models to MK personas based on importance tier.

    Uses the existing LLMRouter for actual API calls but overrides model,
    max_tokens, and temperature per persona tier.
    """

    def __init__(self, router, tier_config: Optional[Dict[str, dict]] = None) -> None:
        """
        Args:
            router: An LLMRouter instance (from app.resources.llm.router).
            tier_config: Optional dict mapping tier name to config overrides.
                         Each value should have keys: provider, model, max_tokens, temperature.
        """
        self.router = router

        # Default tiers — Claude CLI for primary ($0 marginal), Groq for rest
        self.tiers: Dict[str, AgentTier] = {
            "primary": AgentTier(
                tier="primary",
                provider="claude-cli",
                model="sonnet",
                max_tokens=768,
                temperature=0.75,
            ),
            "secondary": AgentTier(
                tier="secondary",
                provider="groq",
                model="llama-3.3-70b-versatile",
                max_tokens=512,
                temperature=0.7,
            ),
            "background": AgentTier(
                tier="background",
                provider="groq",
                model="llama-3.1-8b-instant",
                max_tokens=256,
                temperature=0.6,
            ),
        }

        # Platform-specific routing overrides
        self._platform_overrides: Dict[str, Dict[str, str]] = {
            "negotiation": {"min_tier": "secondary"},
            "brainstorm_divergent": {"force_tier": "background"},
            "decision_devil_advocate": {"force_tier": "primary"},
        }

        # Apply user overrides
        if tier_config:
            for tier_name, cfg in tier_config.items():
                if tier_name in self.tiers:
                    self.tiers[tier_name] = AgentTier(
                        tier=tier_name,
                        provider=cfg.get("provider", self.tiers[tier_name].provider),
                        model=cfg.get("model", self.tiers[tier_name].model),
                        max_tokens=cfg.get("max_tokens", self.tiers[tier_name].max_tokens),
                        temperature=cfg.get("temperature", self.tiers[tier_name].temperature),
                    )

    # ------------------------------------------------------------------
    # Classification
    # ------------------------------------------------------------------

    def classify_agent(
        self,
        persona: KnessetPersona,
        platform: Optional[str] = None,
        role: Optional[str] = None,
    ) -> str:
        """Classify an MK persona into a tier based on importance.

        Primary (key MKs):
            - Influence score >= 85
            - Committee chairs
            - Ministers / PM

        Secondary:
            - Influence score >= 60
            - Faction leaders

        Background:
            - Influence score < 60
            - Regular backbenchers

        Platform overrides:
            - negotiation: all agents minimum secondary
            - brainstorm (divergent): all agents background
            - decision (devil_advocate role): force primary
        """
        # Platform-specific overrides
        if platform and role:
            key = f"{platform}_{role}"
            override = self._platform_overrides.get(key, {})
            if "force_tier" in override:
                return override["force_tier"]

        # Check for high-influence indicators
        is_committee_chair = any(
            "יו\"ר" in role_name or "chair" in role_name.lower()
            for role_name in persona.committee_roles
        )

        # Base classification
        if persona.influence_score >= 85 or is_committee_chair:
            tier = "primary"
        elif persona.influence_score >= 60:
            tier = "secondary"
        else:
            tier = "background"

        # Platform minimum tier enforcement
        if platform:
            override = self._platform_overrides.get(platform, {})
            min_tier = override.get("min_tier")
            if min_tier:
                tier_order = {"primary": 0, "secondary": 1, "background": 2}
                if tier_order.get(tier, 2) > tier_order.get(min_tier, 2):
                    tier = min_tier

        return tier

    def get_tier_config(
        self,
        persona: KnessetPersona,
        platform: Optional[str] = None,
        role: Optional[str] = None,
    ) -> AgentTier:
        """Get the LLM tier config for a specific persona."""
        tier_name = self.classify_agent(persona, platform=platform, role=role)
        return self.tiers[tier_name]

    # ------------------------------------------------------------------
    # LLM interaction
    # ------------------------------------------------------------------

    async def chat_for_agent(
        self,
        persona: KnessetPersona,
        messages: list,
    ) -> str:
        """Route an LLM call through the appropriate tier for this persona.

        Uses router.chat() with tier-specific model, max_tokens, temperature.
        """
        tier = self.get_tier_config(persona)

        try:
            result = self.router.chat(
                task_type="knesset_decision",
                messages=messages,
                temperature=tier.temperature,
                max_tokens=tier.max_tokens,
            )
            return result
        except Exception as exc:
            logger.warning(
                "LLM call failed for %s (tier=%s): %s",
                persona.name_he, tier.tier, exc,
            )
            return '{"action": "DO_NOTHING", "reasoning": "LLM call failed"}'

    # ------------------------------------------------------------------
    # Cost estimation
    # ------------------------------------------------------------------

    def get_cost_estimate(
        self,
        personas: List[KnessetPersona],
        rounds: int,
    ) -> dict:
        """Estimate total cost by tier breakdown.

        Returns dict with counts per tier and rough cost estimate based on
        average prompt size (~500 input tokens, tier.max_tokens output).
        """
        counts: Dict[str, int] = {"primary": 0, "secondary": 0, "background": 0}
        for p in personas:
            tier_name = self.classify_agent(p)
            counts[tier_name] += 1

        # Rough token estimates per call
        avg_input_tokens = 500
        total_calls = len(personas) * rounds

        # Estimate cost per tier (using router's cost tracker pricing if available)
        estimated_cost = 0.0
        tier_details: Dict[str, dict] = {}
        for tier_name, count in counts.items():
            tier = self.tiers[tier_name]
            calls = count * rounds

            # Try to get pricing from router
            pricing = getattr(self.router, "cost_tracker", None)
            input_rate = 0.0
            output_rate = 0.0
            if pricing and hasattr(pricing, "_pricing"):
                p_info = pricing._pricing.get(tier.provider, {})
                input_rate = p_info.get("input_per_1m", 0.0)
                output_rate = p_info.get("output_per_1m", 0.0)

            tier_cost = calls * (
                (avg_input_tokens / 1_000_000) * input_rate
                + (tier.max_tokens / 1_000_000) * output_rate
            )
            estimated_cost += tier_cost

            tier_details[tier_name] = {
                "count": count,
                "calls": calls,
                "model": tier.model,
                "max_tokens": tier.max_tokens,
                "estimated_cost_usd": round(tier_cost, 4),
            }

        return {
            "total_personas": len(personas),
            "rounds": rounds,
            "total_calls": total_calls,
            "tiers": tier_details,
            "estimated_total_cost_usd": round(estimated_cost, 4),
        }

    # ------------------------------------------------------------------
    # Runtime reconfiguration
    # ------------------------------------------------------------------

    def set_tier_model(self, tier: str, provider: str, model: str) -> None:
        """Allow runtime reconfiguration of a tier's model.

        Useful for upgrading primary tier to Claude Opus or downgrading
        background tier to a smaller model mid-session.
        """
        if tier not in self.tiers:
            raise ValueError(f"Unknown tier: {tier}. Must be one of: {list(self.tiers.keys())}")

        old = self.tiers[tier]
        self.tiers[tier] = AgentTier(
            tier=tier,
            provider=provider,
            model=model,
            max_tokens=old.max_tokens,
            temperature=old.temperature,
        )
        logger.info(
            "Tier '%s' model changed: %s/%s -> %s/%s",
            tier, old.provider, old.model, provider, model,
        )
