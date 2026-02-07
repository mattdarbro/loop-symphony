"""Context compaction strategies (Phase 3G).

Manages context size when compositions accumulate large findings lists.
Provides multiple strategies for reducing context while preserving key information.
"""

import logging
from enum import Enum
from typing import Protocol

from pydantic import BaseModel, Field

from loop_symphony.models.finding import Finding

logger = logging.getLogger(__name__)


class CompactionStrategy(str, Enum):
    """Available compaction strategies."""

    SUMMARIZE = "summarize"  # Chunk and summarize findings
    PRUNE = "prune"  # Drop low-relevance findings
    SELECTIVE = "selective"  # Keep marked, compress others
    HYBRID = "hybrid"  # Combine strategies based on content


class CompactionConfig(BaseModel):
    """Configuration for compaction."""

    strategy: CompactionStrategy = CompactionStrategy.HYBRID
    max_findings: int = 50  # Target max findings after compaction
    min_confidence: float = 0.5  # Minimum confidence to keep in pruning
    chunk_size: int = 10  # Findings per chunk for summarization
    preserve_high_confidence: bool = True  # Always keep high-confidence findings
    high_confidence_threshold: float = 0.9


class CompactedFinding(BaseModel):
    """A finding that may have been compacted."""

    content: str
    source: str | None = None
    confidence: float = 1.0
    is_summary: bool = False  # True if this is a summary of multiple findings
    original_count: int = 1  # How many findings this represents
    preserved: bool = False  # True if marked as "must keep"


class CompactionResult(BaseModel):
    """Result of a compaction operation."""

    findings: list[CompactedFinding]
    original_count: int
    final_count: int
    strategy_used: CompactionStrategy
    bytes_saved: int = 0

    @property
    def compression_ratio(self) -> float:
        """How much the findings were compressed."""
        if self.original_count == 0:
            return 1.0
        return self.final_count / self.original_count


class SummarizerProtocol(Protocol):
    """Protocol for summarization capability."""

    async def summarize(self, text: str) -> str:
        """Summarize the given text."""
        ...


class Compactor:
    """Compacts findings using various strategies.

    Strategies:
    - SUMMARIZE: Groups findings into chunks, summarizes each chunk
    - PRUNE: Removes low-confidence findings
    - SELECTIVE: Keeps preserved findings, summarizes others
    - HYBRID: Uses confidence to decide between strategies
    """

    def __init__(
        self,
        summarizer: SummarizerProtocol | None = None,
        config: CompactionConfig | None = None,
    ) -> None:
        """Initialize the compactor.

        Args:
            summarizer: Optional summarizer for SUMMARIZE strategy.
                       If not provided, summarization falls back to truncation.
            config: Compaction configuration
        """
        self._summarizer = summarizer
        self._config = config or CompactionConfig()

    async def compact(
        self,
        findings: list[Finding],
        strategy: CompactionStrategy | None = None,
        config: CompactionConfig | None = None,
    ) -> CompactionResult:
        """Compact a list of findings.

        Args:
            findings: The findings to compact
            strategy: Override strategy (uses config default if None)
            config: Override config

        Returns:
            CompactionResult with compacted findings
        """
        cfg = config or self._config
        strat = strategy or cfg.strategy

        original_count = len(findings)
        original_bytes = sum(len(f.content) for f in findings)

        # No need to compact if already small enough
        if len(findings) <= cfg.max_findings:
            return CompactionResult(
                findings=[self._to_compacted(f) for f in findings],
                original_count=original_count,
                final_count=len(findings),
                strategy_used=strat,
                bytes_saved=0,
            )

        # Apply the selected strategy
        if strat == CompactionStrategy.SUMMARIZE:
            compacted = await self._summarize_strategy(findings, cfg)
        elif strat == CompactionStrategy.PRUNE:
            compacted = self._prune_strategy(findings, cfg)
        elif strat == CompactionStrategy.SELECTIVE:
            compacted = await self._selective_strategy(findings, cfg)
        else:  # HYBRID
            compacted = await self._hybrid_strategy(findings, cfg)

        final_bytes = sum(len(f.content) for f in compacted)

        return CompactionResult(
            findings=compacted,
            original_count=original_count,
            final_count=len(compacted),
            strategy_used=strat,
            bytes_saved=max(0, original_bytes - final_bytes),
        )

    def _to_compacted(self, finding: Finding) -> CompactedFinding:
        """Convert a Finding to CompactedFinding."""
        return CompactedFinding(
            content=finding.content,
            source=finding.source,
            confidence=finding.confidence,
            is_summary=False,
            original_count=1,
        )

    async def _summarize_strategy(
        self,
        findings: list[Finding],
        config: CompactionConfig,
    ) -> list[CompactedFinding]:
        """Summarize findings in chunks.

        Groups findings and creates a summary of each group.
        """
        # Sort by confidence (highest first) to keep best in early chunks
        sorted_findings = sorted(findings, key=lambda f: f.confidence, reverse=True)

        # Preserve high-confidence findings
        preserved: list[CompactedFinding] = []
        to_summarize: list[Finding] = []

        if config.preserve_high_confidence:
            for f in sorted_findings:
                if f.confidence >= config.high_confidence_threshold:
                    preserved.append(self._to_compacted(f))
                    preserved[-1].preserved = True
                else:
                    to_summarize.append(f)
        else:
            to_summarize = sorted_findings

        # Chunk and summarize
        chunks = [
            to_summarize[i : i + config.chunk_size]
            for i in range(0, len(to_summarize), config.chunk_size)
        ]

        summaries: list[CompactedFinding] = []
        for chunk in chunks:
            summary = await self._summarize_chunk(chunk)
            summaries.append(summary)

        # Combine preserved and summaries, respecting max
        result = preserved + summaries
        if len(result) > config.max_findings:
            result = result[: config.max_findings]

        return result

    async def _summarize_chunk(self, chunk: list[Finding]) -> CompactedFinding:
        """Summarize a chunk of findings."""
        combined_text = "\n\n".join(f.content for f in chunk)
        avg_confidence = sum(f.confidence for f in chunk) / len(chunk)
        sources = list({f.source for f in chunk if f.source})

        if self._summarizer:
            summary_text = await self._summarizer.summarize(combined_text)
        else:
            # Fallback: truncate if no summarizer
            summary_text = self._truncate(combined_text, max_chars=500)

        return CompactedFinding(
            content=summary_text,
            source=", ".join(sources[:3]) if sources else None,
            confidence=avg_confidence,
            is_summary=True,
            original_count=len(chunk),
        )

    def _truncate(self, text: str, max_chars: int = 500) -> str:
        """Truncate text to max characters."""
        if len(text) <= max_chars:
            return text
        return text[: max_chars - 3] + "..."

    def _prune_strategy(
        self,
        findings: list[Finding],
        config: CompactionConfig,
    ) -> list[CompactedFinding]:
        """Prune low-confidence findings.

        Keeps findings above the confidence threshold, sorted by confidence.
        """
        # Filter by confidence
        filtered = [f for f in findings if f.confidence >= config.min_confidence]

        # Sort by confidence (highest first)
        sorted_findings = sorted(filtered, key=lambda f: f.confidence, reverse=True)

        # Take top N
        kept = sorted_findings[: config.max_findings]

        return [self._to_compacted(f) for f in kept]

    async def _selective_strategy(
        self,
        findings: list[Finding],
        config: CompactionConfig,
    ) -> list[CompactedFinding]:
        """Selective compaction: keep high-confidence, summarize rest.

        Similar to summarize but more aggressive about preserving
        high-confidence findings.
        """
        # Split into preserve and compress
        to_preserve: list[Finding] = []
        to_compress: list[Finding] = []

        for f in findings:
            if f.confidence >= config.high_confidence_threshold:
                to_preserve.append(f)
            else:
                to_compress.append(f)

        preserved = [self._to_compacted(f) for f in to_preserve]
        for p in preserved:
            p.preserved = True

        # Budget for summaries
        summary_budget = max(1, config.max_findings - len(preserved))

        if not to_compress:
            return preserved[: config.max_findings]

        # Summarize all low-confidence findings into fewer summaries
        chunks_needed = min(summary_budget, max(1, len(to_compress) // config.chunk_size))
        chunk_size = max(1, len(to_compress) // chunks_needed)

        chunks = [
            to_compress[i : i + chunk_size]
            for i in range(0, len(to_compress), chunk_size)
        ]

        summaries: list[CompactedFinding] = []
        for chunk in chunks[:summary_budget]:
            summary = await self._summarize_chunk(chunk)
            summaries.append(summary)

        return (preserved + summaries)[: config.max_findings]

    async def _hybrid_strategy(
        self,
        findings: list[Finding],
        config: CompactionConfig,
    ) -> list[CompactedFinding]:
        """Hybrid strategy: choose based on findings characteristics.

        - If mostly high-confidence: use prune
        - If mixed confidence: use selective
        - If mostly low-confidence: use summarize
        """
        if not findings:
            return []

        avg_confidence = sum(f.confidence for f in findings) / len(findings)
        high_conf_count = sum(
            1 for f in findings if f.confidence >= config.high_confidence_threshold
        )
        high_conf_ratio = high_conf_count / len(findings)

        if high_conf_ratio > 0.7:
            # Mostly high confidence - just prune
            logger.debug("Hybrid: using prune (high confidence ratio)")
            return self._prune_strategy(findings, config)
        elif high_conf_ratio > 0.3:
            # Mixed - use selective
            logger.debug("Hybrid: using selective (mixed confidence)")
            return await self._selective_strategy(findings, config)
        else:
            # Mostly low confidence - summarize aggressively
            logger.debug("Hybrid: using summarize (low confidence)")
            return await self._summarize_strategy(findings, config)

    def score_relevance(
        self,
        finding: Finding,
        query: str | None = None,
    ) -> float:
        """Score a finding's relevance.

        Currently uses confidence as a proxy for relevance.
        Could be extended to use semantic similarity with query.

        Args:
            finding: The finding to score
            query: Optional query for semantic matching

        Returns:
            Relevance score 0-1
        """
        # Base score is confidence
        score = finding.confidence

        # Could add query similarity here in the future
        # if query and self._embedder:
        #     similarity = self._embedder.similarity(finding.content, query)
        #     score = (score + similarity) / 2

        return score


def select_strategy(
    findings: list[Finding],
    context_type: str | None = None,
) -> CompactionStrategy:
    """Select the best compaction strategy for the given context.

    Args:
        findings: The findings to compact
        context_type: Optional hint about the context type

    Returns:
        The recommended CompactionStrategy
    """
    if not findings:
        return CompactionStrategy.PRUNE

    # Check confidence distribution
    avg_confidence = sum(f.confidence for f in findings) / len(findings)
    high_conf_count = sum(1 for f in findings if f.confidence >= 0.9)
    high_conf_ratio = high_conf_count / len(findings)

    # Context-based selection
    if context_type == "research":
        # Research benefits from summaries
        return CompactionStrategy.SUMMARIZE
    elif context_type == "fact_check":
        # Fact checking needs high-confidence facts
        return CompactionStrategy.SELECTIVE
    elif context_type == "quick":
        # Quick responses just need top results
        return CompactionStrategy.PRUNE

    # Confidence-based fallback
    if high_conf_ratio > 0.5:
        return CompactionStrategy.PRUNE
    elif avg_confidence < 0.6:
        return CompactionStrategy.SUMMARIZE
    else:
        return CompactionStrategy.HYBRID
