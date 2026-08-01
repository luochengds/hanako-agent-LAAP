"""LLM-as-a-Verifier integration for LAAP.

Implements the core idea from arXiv:2607.05391:
    - Use fine-grained scoring tokens (letters A-T mapped to 1-20).
    - Compute the expectation over the full logprob distribution.
    - Scale via granularity, repeated evaluation, and criteria decomposition.

This module is designed to be usable standalone and inside AEvo.
"""

from __future__ import annotations

import asyncio
import logging
import math
import os
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from laap.llm.transports import OpenAITransport

logger = logging.getLogger("laap.verification.llm_verifier")


@dataclass
class VerifierConfig:
    """Configuration for LLM-as-a-Verifier."""

    provider: str = "openai"
    model: str = "gpt-4o-mini"
    api_key: Optional[str] = None
    base_url: Optional[str] = None
    granularity: int = 20
    n_verifications: int = 2
    criteria: List[str] = field(
        default_factory=lambda: [
            "correctness",
            "safety",
            "efficiency",
        ]
    )
    temperature: float = 0.0
    max_tokens: int = 8
    # When True, use a deterministic mock logprob distribution. Useful for
    # tests and for environments without an API key.
    mock: bool = False


@dataclass
class VerifierScore:
    """Result of a single verifier evaluation."""

    score: float
    # Per-criterion breakdown.
    criteria_scores: Dict[str, float]
    # Raw logprob distribution for the first verification pass.
    logprobs: Optional[Dict[str, float]]
    # Number of API calls made.
    calls: int
    # Optional metadata (e.g. token usage).
    metadata: Dict[str, Any] = field(default_factory=dict)


class LLMVerifier:
    """Probabilistic verifier using scoring-token logprobs.

    Score tokens are uppercase letters A, B, C, ... mapped linearly to the
    interval [1/granularity, 1.0].  Using letters instead of digits makes it
    much more likely that each score level corresponds to a single token and
    therefore has an extractable logprob.
    """

    def __init__(self, config: Optional[VerifierConfig] = None) -> None:
        self.config = config or VerifierConfig()
        self._score_tokens = self._build_score_tokens(self.config.granularity)
        self._transport: Optional[OpenAITransport] = None
        if not self.config.mock and self.config.provider == "openai":
            self._transport = OpenAITransport(
                api_key=self.config.api_key,
                model=self.config.model,
            )

    def _build_score_tokens(self, granularity: int) -> Dict[str, float]:
        """Map letters A.. to scalar scores 1/granularity..1.0."""
        tokens: Dict[str, float] = {}
        for i in range(granularity):
            letter = chr(ord("A") + i)
            tokens[letter] = (i + 1) / granularity
        return tokens

    def _format_candidate(self, candidate: Any) -> str:
        """Normalize a candidate object to a string for the prompt."""
        if isinstance(candidate, str):
            return candidate
        if isinstance(candidate, dict):
            return "\n".join(f"{k}: {v}" for k, v in candidate.items())
        return str(candidate)

    def _build_score_prompt(
        self,
        task: str,
        candidate: str,
        criterion: str,
    ) -> List[Dict[str, str]]:
        """Build the chat messages for a single-criterion score call."""
        criteria_desc = {
            "correctness": "Does the candidate correctly solve the task?",
            "safety": "Does the candidate avoid harmful or destructive operations?",
            "efficiency": "Is the candidate concise and avoids waste?",
        }
        description = criteria_desc.get(criterion, f"Evaluate the candidate on: {criterion}")
        tokens = ", ".join(self._score_tokens.keys())
        return [
            {
                "role": "system",
                "content": (
                    "You are an expert reviewer. Rate the candidate solution on a single "
                    "criterion. Respond with exactly one uppercase letter from the allowed "
                    "score set. Do not add explanation."
                ),
            },
            {
                "role": "user",
                "content": (
                    f"Task:\n{task}\n\n"
                    f"Candidate Solution:\n{candidate}\n\n"
                    f"Criterion: {criterion}\n"
                    f"{description}\n\n"
                    f"Allowed scores (A=lowest, {list(self._score_tokens.keys())[-1]}=highest): {tokens}\n"
                    "Final score (single letter):"
                ),
            },
        ]

    def _normalize_logprobs(self, raw: Optional[Dict[str, float]]) -> Dict[str, float]:
        """Softmax-normalize logprobs over the allowed score-token set.

        The returned distribution contains every allowed score token. Missing
        tokens receive zero probability mass after normalization.
        """
        allowed = set(self._score_tokens.keys())
        if not raw:
            n = len(allowed)
            return {t: 1.0 / n for t in allowed}

        filtered = {t: lp for t, lp in raw.items() if t in allowed}
        if not filtered:
            n = len(allowed)
            return {t: 1.0 / n for t in allowed}

        # Numerically stable softmax over the filtered tokens.
        max_lp = max(filtered.values())
        exps = {t: math.exp(lp - max_lp) for t, lp in filtered.items()}
        total = sum(exps.values())
        probs = {t: e / total for t, e in exps.items()}

        # Ensure all allowed tokens appear in the output distribution.
        for token in allowed:
            probs.setdefault(token, 0.0)
        return probs

    def _expected_score(self, probs: Dict[str, float]) -> float:
        """Compute E[score] over the token distribution."""
        return sum(probs.get(t, 0.0) * value for t, value in self._score_tokens.items())

    def _mock_logprobs(self, candidate: str, criterion: str) -> Dict[str, float]:
        """Deterministic mock logprobs for testing without an API."""
        text = f" {candidate} : {criterion} ".lower()
        # Use whitespace-delimited word checks to avoid matching ``safe`` inside
        # ``unsafe``.
        words = set(text.split())
        if words & {"good", "correct", "safe"}:
            quality = 0.85
        elif words & {"bad", "error", "unsafe"}:
            quality = 0.15
        elif words & {"partial", "ok"}:
            quality = 0.5
        else:
            quality = 0.5

        # Shift the distribution toward the quality level.
        target_index = int(quality * (self.config.granularity - 1))
        logprobs: Dict[str, float] = {}
        for i, token in enumerate(self._score_tokens):
            distance = abs(i - target_index)
            logprobs[token] = -distance * 1.5 + (1.0 if i == target_index else 0.0)
        return logprobs

    async def _call_api(
        self,
        task: str,
        candidate: str,
        criterion: str,
    ) -> Dict[str, float]:
        """Make one API call and return the logprob distribution."""
        if self.config.mock:
            return self._mock_logprobs(candidate, criterion)

        if self._transport is None:
            raise RuntimeError("No transport available and mock mode is disabled")

        messages = self._build_score_prompt(task, candidate, criterion)
        response = await self._transport.generate(
            messages,
            max_tokens=self.config.max_tokens,
            temperature=self.config.temperature,
            logprobs=True,
            top_logprobs=self.config.granularity,
        )
        return response.logprobs or {}

    async def score(
        self,
        task: str,
        candidate: Any,
        criteria: Optional[List[str]] = None,
    ) -> VerifierScore:
        """Score a single candidate using criteria decomposition and repeats.

        Returns a VerifierScore where ``score`` is the average expected score
        across all criteria and repetitions, normalized to [0, 1].
        """
        candidate_str = self._format_candidate(candidate)
        criteria = criteria or self.config.criteria
        criteria_scores: Dict[str, float] = {}
        total_score = 0.0
        calls = 0
        first_logprobs: Optional[Dict[str, float]] = None

        for criterion in criteria:
            criterion_total = 0.0
            for _ in range(self.config.n_verifications):
                raw_logprobs = await self._call_api(task, candidate_str, criterion)
                probs = self._normalize_logprobs(raw_logprobs)
                if first_logprobs is None:
                    first_logprobs = raw_logprobs
                criterion_total += self._expected_score(probs)
                calls += 1
            criterion_score = criterion_total / self.config.n_verifications
            criteria_scores[criterion] = criterion_score
            total_score += criterion_score

        final_score = total_score / len(criteria) if criteria else 0.0
        return VerifierScore(
            score=final_score,
            criteria_scores=criteria_scores,
            logprobs=first_logprobs,
            calls=calls,
            metadata={
                "granularity": self.config.granularity,
                "n_verifications": self.config.n_verifications,
                "criteria": criteria,
            },
        )

    async def compare(
        self,
        task: str,
        candidate_a: Any,
        candidate_b: Any,
    ) -> Tuple[Any, Dict[str, Any]]:
        """Pairwise comparison: returns the better candidate and details."""
        score_a = await self.score(task, candidate_a)
        score_b = await self.score(task, candidate_b)
        winner = candidate_a if score_a.score >= score_b.score else candidate_b
        return winner, {
            "winner_score": max(score_a.score, score_b.score),
            "loser_score": min(score_a.score, score_b.score),
            "score_a": score_a,
            "score_b": score_b,
        }

    async def select(
        self,
        task: str,
        candidates: List[Any],
    ) -> Tuple[Any, Dict[str, Any]]:
        """Round-robin tournament selection (Best-of-N).

        Each candidate is compared against every other candidate. The candidate
        with the most pairwise wins is returned. Ties are broken by average
        margin.
        """
        if not candidates:
            raise ValueError("select() requires at least one candidate")
        if len(candidates) == 1:
            score = await self.score(task, candidates[0])
            return candidates[0], {"score": score, "wins": 0, "matches": 0}

        scores: Dict[int, float] = {}
        for idx, candidate in enumerate(candidates):
            verifier_score = await self.score(task, candidate)
            scores[idx] = verifier_score.score

        wins = [0] * len(candidates)
        margins = [0.0] * len(candidates)
        matches = 0
        for i in range(len(candidates)):
            for j in range(i + 1, len(candidates)):
                matches += 1
                if scores[i] > scores[j]:
                    wins[i] += 1
                    margins[i] += scores[i] - scores[j]
                elif scores[j] > scores[i]:
                    wins[j] += 1
                    margins[j] += scores[j] - scores[i]
                else:
                    # Tie: both get half a win.
                    wins[i] += 0.5
                    wins[j] += 0.5

        best_idx = max(
            range(len(candidates)),
            key=lambda i: (wins[i], margins[i], scores[i]),
        )
        return candidates[best_idx], {
            "score": scores[best_idx],
            "wins": wins[best_idx],
            "matches": matches,
            "all_scores": {idx: s for idx, s in scores.items()},
        }

    def score_sync(
        self,
        task: str,
        candidate: Any,
        criteria: Optional[List[str]] = None,
    ) -> VerifierScore:
        """Synchronous wrapper around :meth:`score`."""
        coro = self.score(task, candidate, criteria=criteria)
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return asyncio.run(coro)
        # If we are already in an async context, schedule the coroutine.
        return loop.run_until_complete(coro)

    def compare_sync(
        self,
        task: str,
        candidate_a: Any,
        candidate_b: Any,
    ) -> Tuple[Any, Dict[str, Any]]:
        """Synchronous wrapper around :meth:`compare`."""
        coro = self.compare(task, candidate_a, candidate_b)
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return asyncio.run(coro)
        return loop.run_until_complete(coro)

    def select_sync(
        self,
        task: str,
        candidates: List[Any],
    ) -> Tuple[Any, Dict[str, Any]]:
        """Synchronous wrapper around :meth:`select`."""
        coro = self.select(task, candidates)
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return asyncio.run(coro)
        return loop.run_until_complete(coro)


# Convenience: build a verifier from environment variables.
def verifier_from_env(
    granularity: int = 20,
    n_verifications: int = 2,
    criteria: Optional[List[str]] = None,
) -> LLMVerifier:
    """Create a verifier using LAAP_* / provider-specific env vars."""
    provider = os.environ.get("LAAP_PROVIDER", "openai").lower()
    model = os.environ.get("LAAP_MODEL", "gpt-4o-mini")
    api_key = os.environ.get("LAAP_API_KEY")
    base_url = os.environ.get("LAAP_BASE_URL")
    return LLMVerifier(
        VerifierConfig(
            provider=provider,
            model=model,
            api_key=api_key,
            base_url=base_url,
            granularity=granularity,
            n_verifications=n_verifications,
            criteria=criteria or VerifierConfig().criteria,
        )
    )
