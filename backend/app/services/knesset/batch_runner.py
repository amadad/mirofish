"""BatchParallelRunner — runs multiple MK agents simultaneously with
configurable concurrency and rate limiting.

Replaces the simple batch loop in KnessetLoop with proper async
concurrency control via semaphore + token-bucket rate limiter.
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any, Callable, Dict, List, Optional

from .multi_model_router import AgentModelRouter
from .types import KnessetAction, KnessetPersona

logger = logging.getLogger("mirofish.knesset.batch_runner")


# ---------------------------------------------------------------------------
# AsyncRateLimiter — token bucket
# ---------------------------------------------------------------------------

class AsyncRateLimiter:
    """Token-bucket rate limiter for async API calls.

    Ensures we don't exceed a given requests-per-second rate, smoothing
    bursts across the time window.
    """

    def __init__(self, rps: int) -> None:
        self.rps = max(1, rps)
        self._tokens = float(self.rps)
        self._max_tokens = float(self.rps)
        self._last_refill = time.monotonic()
        self._lock = asyncio.Lock()

    def _refill(self) -> None:
        """Add tokens based on elapsed time since last refill."""
        now = time.monotonic()
        elapsed = now - self._last_refill
        self._tokens = min(self._max_tokens, self._tokens + elapsed * self.rps)
        self._last_refill = now

    async def acquire(self) -> None:
        """Wait until a token is available, then consume one."""
        while True:
            async with self._lock:
                self._refill()
                if self._tokens >= 1.0:
                    self._tokens -= 1.0
                    return
            # Sleep briefly before retrying
            await asyncio.sleep(1.0 / self.rps)


# ---------------------------------------------------------------------------
# BatchParallelRunner
# ---------------------------------------------------------------------------

class BatchParallelRunner:
    """Runs multiple MK agents in parallel with concurrency and rate limits.

    Usage:
        runner = BatchParallelRunner(agent_model_router, concurrency=10)
        actions = await runner.run_batch(
            personas, build_prompt_fn, parse_response_fn, round_num=1
        )
    """

    def __init__(
        self,
        agent_model_router: AgentModelRouter,
        concurrency: int = 10,
        rate_limit_rps: int = 30,
    ) -> None:
        self.router = agent_model_router
        self.concurrency = concurrency
        self.rate_limit_rps = rate_limit_rps
        self._semaphore = asyncio.Semaphore(concurrency)
        self._rate_limiter = AsyncRateLimiter(rate_limit_rps)

        # Throughput tracking
        self._total_processed: int = 0
        self._total_errors: int = 0
        self._latencies: List[float] = []
        self._start_time: Optional[float] = None

    # ------------------------------------------------------------------
    # Batch execution
    # ------------------------------------------------------------------

    async def run_batch(
        self,
        personas: List[KnessetPersona],
        build_prompt_fn: Callable[[KnessetPersona, int], str],
        parse_response_fn: Callable[[str, KnessetPersona, int], KnessetAction],
        round_num: int,
    ) -> List[KnessetAction]:
        """Process ALL personas with concurrency limit and rate limiting.

        Args:
            personas: List of MK personas to process.
            build_prompt_fn: Callable(persona, round_num) -> prompt string.
            parse_response_fn: Callable(response_text, persona, round_num) -> KnessetAction.
            round_num: Current simulation round number.

        Returns:
            List of valid KnessetActions (errors are logged and filtered out).
        """
        self._start_time = time.monotonic()

        tasks = [
            self._process_agent(persona, build_prompt_fn, parse_response_fn, round_num)
            for persona in personas
        ]

        results = await asyncio.gather(*tasks, return_exceptions=True)

        # Filter out exceptions
        actions: List[KnessetAction] = []
        for i, result in enumerate(results):
            if isinstance(result, Exception):
                self._total_errors += 1
                logger.warning(
                    "Agent %s failed in round %d: %s",
                    personas[i].name_he, round_num, result,
                )
            elif result is not None:
                actions.append(result)

        elapsed = time.monotonic() - self._start_time
        logger.info(
            "Batch round %d complete: %d/%d succeeded in %.1fs (%.1f agents/sec)",
            round_num, len(actions), len(personas), elapsed,
            len(actions) / elapsed if elapsed > 0 else 0,
        )

        return actions

    async def _process_agent(
        self,
        persona: KnessetPersona,
        build_prompt_fn: Callable[[KnessetPersona, int], str],
        parse_response_fn: Callable[[str, KnessetPersona, int], KnessetAction],
        round_num: int,
    ) -> KnessetAction:
        """Process a single agent with semaphore + rate limit."""
        async with self._semaphore:
            await self._rate_limiter.acquire()

            start = time.monotonic()

            prompt = build_prompt_fn(persona, round_num)
            response = await self.router.chat_for_agent(
                persona, [{"role": "user", "content": prompt}]
            )
            action = parse_response_fn(response, persona, round_num)

            latency = time.monotonic() - start
            self._latencies.append(latency)
            self._total_processed += 1

            return action

    # ------------------------------------------------------------------
    # Throughput stats
    # ------------------------------------------------------------------

    def get_throughput_stats(self) -> dict:
        """Return throughput and error statistics."""
        avg_latency = (
            sum(self._latencies) / len(self._latencies)
            if self._latencies else 0.0
        )

        elapsed = 0.0
        if self._start_time is not None:
            elapsed = time.monotonic() - self._start_time

        agents_per_second = (
            self._total_processed / elapsed if elapsed > 0 else 0.0
        )

        return {
            "total_processed": self._total_processed,
            "total_errors": self._total_errors,
            "error_rate": (
                self._total_errors / (self._total_processed + self._total_errors)
                if (self._total_processed + self._total_errors) > 0 else 0.0
            ),
            "agents_per_second": round(agents_per_second, 2),
            "avg_latency_seconds": round(avg_latency, 3),
            "min_latency_seconds": round(min(self._latencies), 3) if self._latencies else 0.0,
            "max_latency_seconds": round(max(self._latencies), 3) if self._latencies else 0.0,
            "concurrency": self.concurrency,
            "rate_limit_rps": self.rate_limit_rps,
        }

    def reset_stats(self) -> None:
        """Reset throughput counters for a fresh measurement window."""
        self._total_processed = 0
        self._total_errors = 0
        self._latencies.clear()
        self._start_time = None
