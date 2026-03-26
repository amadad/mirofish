"""SocialLayer -- Twitter-like overlay for Knesset simulations.

Runs after each KnessetLoop round. Agents who took notable actions
may tweet about them. Journalists analyze, tycoons react, others engage.
"""

from __future__ import annotations

import logging
import random
import uuid
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

logger = logging.getLogger("mirofish.knesset.social_layer")


@dataclass
class SimTweet:
    """A simulated tweet from an agent."""

    tweet_id: str
    agent_id: str
    agent_name: str
    agent_role: str  # "mk", "journalist", "tycoon", "activist"
    content_he: str
    round_num: int
    timestamp: str = ""
    likes: int = 0
    retweets: int = 0
    replies: int = 0
    reply_to: Optional[str] = None  # tweet_id this replies to
    hashtags: List[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "tweet_id": self.tweet_id,
            "agent_id": self.agent_id,
            "agent_name": self.agent_name,
            "agent_role": self.agent_role,
            "content_he": self.content_he,
            "round_num": self.round_num,
            "timestamp": self.timestamp,
            "likes": self.likes,
            "retweets": self.retweets,
            "replies": self.replies,
            "reply_to": self.reply_to,
            "hashtags": self.hashtags,
        }


class SocialLayer:
    """Twitter-like overlay that runs after each KnessetLoop round."""

    def __init__(
        self,
        router: Any,
        personas: list,
        auxiliary_agents: Optional[list] = None,
        tweet_probability: float = 0.4,
    ) -> None:
        self.router = router
        self.personas: Dict[str, Any] = {p.agent_id: p for p in personas}
        self.auxiliary_agents = auxiliary_agents or []
        self.tweet_probability = tweet_probability
        self.all_tweets: List[SimTweet] = []
        self.round_tweets: Dict[int, List[SimTweet]] = {}
        self._engagement_log: List[dict] = []

    async def process_round(
        self, round_num: int, round_actions: List[dict]
    ) -> List[dict]:
        """After a KnessetLoop round, generate social media reactions.

        Args:
            round_num: Current round number
            round_actions: List of KnessetAction.to_dict() from this round

        Returns:
            List of SimTweet dicts generated this round
        """
        new_tweets: List[SimTweet] = []

        # 1. MKs who acted (not DO_NOTHING) might tweet (40% chance)
        for action in round_actions:
            if action.get("action_type") == "DO_NOTHING":
                continue
            if random.random() < self.tweet_probability:
                tweet = self._generate_mk_tweet(action, round_num)
                new_tweets.append(tweet)

        # 2. Journalists always tweet analysis
        for agent in self.auxiliary_agents:
            if hasattr(agent, "role") and agent.role == "journalist":
                tweet = self._generate_journalist_tweet(
                    agent, round_actions, round_num
                )
                if tweet:
                    new_tweets.append(tweet)

        # 3. Tycoons react if economic topics involved
        for agent in self.auxiliary_agents:
            if hasattr(agent, "role") and agent.role == "tycoon":
                if self._is_economically_relevant(round_actions):
                    tweet = self._generate_tycoon_tweet(
                        agent, round_actions, round_num
                    )
                    if tweet:
                        new_tweets.append(tweet)

        # 4. Simulate engagement (likes, RTs) on new tweets
        self._simulate_engagement(new_tweets, round_num)

        # Store
        self.all_tweets.extend(new_tweets)
        self.round_tweets[round_num] = new_tweets

        logger.info(
            "Social layer round %d: %d tweets generated", round_num, len(new_tweets)
        )

        return [t.to_dict() for t in new_tweets]

    # ------------------------------------------------------------------
    # Tweet generation
    # ------------------------------------------------------------------

    def _generate_mk_tweet(self, action: dict, round_num: int) -> SimTweet:
        """Generate a tweet from an MK about their action."""
        action_type = action.get("action_type", "")
        agent_name = action.get("agent_name", "")
        reasoning = action.get("reasoning", "")
        speech = action.get("speech_text", "")
        bill_id = action.get("bill_id", "")
        vote = action.get("vote_value", "")

        # Build tweet content based on action type
        content_templates = {
            "VOTE": f"\u05d4\u05e6\u05d1\u05e2\u05ea\u05d9 {vote} \u05e2\u05dc {bill_id}. {reasoning[:80]}",
            "SPEAK_IN_PLENUM": (
                f"{speech[:120]}" if speech else f"\u05e0\u05d0\u05de\u05ea\u05d9 \u05d1\u05de\u05dc\u05d9\u05d0\u05d4. {reasoning[:80]}"
            ),
            "SPEAK": (
                f"{speech[:120]}" if speech else f"\u05d3\u05d9\u05d1\u05e8\u05ea\u05d9 \u05d1\u05d3\u05d9\u05d5\u05df. {reasoning[:80]}"
            ),
            "PROPOSE_BILL": f"\u05d4\u05d2\u05e9\u05ea\u05d9 \u05d4\u05e6\u05e2\u05ea \u05d7\u05d5\u05e7: {bill_id}. {reasoning[:80]}",
            "LOBBY": f"\u05e9\u05d5\u05d7\u05d7\u05ea\u05d9 \u05e2\u05dd \u05e2\u05de\u05d9\u05ea\u05d9\u05dd \u05e2\u05dc {bill_id or '\u05e0\u05d5\u05e9\u05d0\u05d9\u05dd \u05d7\u05e9\u05d5\u05d1\u05d9\u05dd'}.",
            "FORM_ALLIANCE": f"\u05d4\u05e7\u05de\u05ea\u05d9 \u05e9\u05d9\u05ea\u05d5\u05e3 \u05e4\u05e2\u05d5\u05dc\u05d4 \u05d7\u05d3\u05e9. {reasoning[:80]}",
            "DEFECT": f"\u05e7\u05d9\u05d1\u05dc\u05ea\u05d9 \u05d4\u05d7\u05dc\u05d8\u05d4 \u05e7\u05e9\u05d4. {reasoning[:80]}",
        }
        content = content_templates.get(action_type, reasoning[:120])

        # Extract hashtags from content
        hashtags = self._extract_hashtags(content, action)

        return SimTweet(
            tweet_id=f"tw_{uuid.uuid4().hex[:8]}",
            agent_id=action.get("agent_id", ""),
            agent_name=agent_name,
            agent_role="mk",
            content_he=content,
            round_num=round_num,
            timestamp=datetime.now(timezone.utc).isoformat(),
            hashtags=hashtags,
        )

    def _generate_journalist_tweet(
        self, journalist: Any, actions: List[dict], round_num: int
    ) -> Optional[SimTweet]:
        """Journalist tweets analysis of the round."""
        votes = [a for a in actions if a.get("action_type") == "VOTE"]
        speeches = [
            a
            for a in actions
            if a.get("action_type") in ("SPEAK", "SPEAK_IN_PLENUM")
        ]
        defections = [a for a in actions if a.get("action_type") == "DEFECT"]

        if not votes and not speeches and not defections:
            return None

        # Build analysis content
        parts: List[str] = []
        if votes:
            for_count = sum(1 for v in votes if v.get("vote_value") == "\u05d1\u05e2\u05d3")
            against_count = sum(
                1 for v in votes if v.get("vote_value") == "\u05e0\u05d2\u05d3"
            )
            parts.append(
                f"\u05e1\u05d1\u05d1 {round_num}: {for_count} \u05d1\u05e2\u05d3, {against_count} \u05e0\u05d2\u05d3"
            )
        if defections:
            names = [d.get("agent_name", "?") for d in defections]
            parts.append(f"\u05d7\u05e8\u05d9\u05d2\u05d4 \u05e1\u05d9\u05e2\u05ea\u05d9\u05ea: {', '.join(names)}")
        if speeches:
            top_speech = speeches[0]
            parts.append(f"{top_speech.get('agent_name', '?')} \u05e0\u05d0\u05dd/\u05d4")

        content = " | ".join(parts)

        return SimTweet(
            tweet_id=f"tw_{uuid.uuid4().hex[:8]}",
            agent_id=journalist.agent_id,
            agent_name=journalist.name_he,
            agent_role="journalist",
            content_he=content,
            round_num=round_num,
            timestamp=datetime.now(timezone.utc).isoformat(),
            hashtags=["\u05db\u05e0\u05e1\u05ea#", f"#\u05e1\u05d1\u05d1_{round_num}"],
        )

    def _generate_tycoon_tweet(
        self, tycoon: Any, actions: List[dict], round_num: int
    ) -> Optional[SimTweet]:
        """Tycoon reacts to economic implications."""
        votes = [a for a in actions if a.get("action_type") == "VOTE"]
        if not votes:
            return None

        sector = getattr(tycoon, "affiliation", "\u05e2\u05e1\u05e7\u05d9\u05dd")
        content = (
            f"\u05db{tycoon.name_he} \u05de\u05e1\u05e7\u05d8\u05d5\u05e8 {sector}: "
            f"\u05e2\u05d5\u05e7\u05d1/\u05ea \u05d1\u05d3\u05d0\u05d2\u05d4 \u05d0\u05d7\u05e8\u05d9 \u05d4\u05d4\u05e6\u05d1\u05e2\u05d5\u05ea \u05d1\u05db\u05e0\u05e1\u05ea. "
            f"\u05d4\u05d4\u05e9\u05dc\u05db\u05d5\u05ea \u05d4\u05db\u05dc\u05db\u05dc\u05d9\u05d5\u05ea \u05de\u05e9\u05de\u05e2\u05d5\u05ea\u05d9\u05d5\u05ea."
        )

        return SimTweet(
            tweet_id=f"tw_{uuid.uuid4().hex[:8]}",
            agent_id=tycoon.agent_id,
            agent_name=tycoon.name_he,
            agent_role="tycoon",
            content_he=content,
            round_num=round_num,
            timestamp=datetime.now(timezone.utc).isoformat(),
            hashtags=["\u05db\u05dc\u05db\u05dc\u05d4#", "\u05db\u05e0\u05e1\u05ea#"],
        )

    # ------------------------------------------------------------------
    # Engagement simulation
    # ------------------------------------------------------------------

    def _simulate_engagement(
        self, tweets: List[SimTweet], round_num: int
    ) -> None:
        """Simulate likes and RTs based on agent influence."""
        for tweet in tweets:
            persona = self.personas.get(tweet.agent_id)
            influence = persona.influence_score if persona else 30
            # Higher influence = more engagement
            tweet.likes = random.randint(10, 50) + (influence * 3)
            tweet.retweets = random.randint(2, 20) + (influence // 2)
            tweet.replies = random.randint(1, 10) + (influence // 10)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _is_economically_relevant(self, actions: List[dict]) -> bool:
        """Check if round actions touch economic topics."""
        economic_keywords = [
            "\u05ea\u05e7\u05e6\u05d9\u05d1",
            "\u05de\u05e1",
            "\u05db\u05dc\u05db\u05dc\u05d4",
            "\u05e9\u05db\u05e8",
            "\u05d3\u05d9\u05d5\u05e8",
            "\u05de\u05d7\u05d9\u05e8",
            "\u05d0\u05e0\u05e8\u05d2\u05d9\u05d4",
        ]
        for action in actions:
            text = (
                f"{action.get('reasoning', '')} "
                f"{action.get('speech_text', '')} "
                f"{action.get('bill_id', '')}"
            )
            if any(kw in text for kw in economic_keywords):
                return True
        return random.random() < 0.2  # 20% chance even without keywords

    def _extract_hashtags(self, content: str, action: dict) -> List[str]:
        """Extract relevant hashtags."""
        tags = ["\u05db\u05e0\u05e1\u05ea#"]
        bill_id = action.get("bill_id", "")
        if bill_id:
            clean = bill_id.replace("user_bill_", "").replace("_", "")[:15]
            tags.append(f"#{clean}")
        return tags

    # ------------------------------------------------------------------
    # Analytics
    # ------------------------------------------------------------------

    def get_trending(self, top_n: int = 5) -> List[dict]:
        """Get trending hashtags across all tweets."""
        tag_counts: Counter = Counter()
        for tweet in self.all_tweets:
            for tag in tweet.hashtags:
                tag_counts[tag] += 1
        return [
            {"hashtag": tag, "count": count}
            for tag, count in tag_counts.most_common(top_n)
        ]

    def get_engagement_stats(self) -> dict:
        """Return total engagement metrics."""
        total_likes = sum(t.likes for t in self.all_tweets)
        total_rts = sum(t.retweets for t in self.all_tweets)
        total_replies = sum(t.replies for t in self.all_tweets)
        return {
            "total_tweets": len(self.all_tweets),
            "total_likes": total_likes,
            "total_retweets": total_rts,
            "total_replies": total_replies,
            "top_tweeter": (
                max(
                    (
                        (t.agent_name, t.likes + t.retweets)
                        for t in self.all_tweets
                    ),
                    key=lambda x: x[1],
                    default=("", 0),
                )[0]
                if self.all_tweets
                else ""
            ),
        }

    def get_influence_adjustments(self) -> Dict[str, float]:
        """Agents with high engagement get temporary influence boost."""
        adjustments: Dict[str, float] = {}
        for tweet in self.all_tweets:
            engagement = tweet.likes + tweet.retweets * 2
            if engagement > 100:
                boost = min(5.0, engagement / 50.0)  # max +5 influence
                current = adjustments.get(tweet.agent_id, 0.0)
                adjustments[tweet.agent_id] = max(current, boost)
        return adjustments
