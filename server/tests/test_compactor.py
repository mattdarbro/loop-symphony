"""Tests for context compaction (Phase 3G)."""

import pytest
from datetime import datetime, UTC

from loop_symphony.manager.compactor import (
    CompactedFinding,
    CompactionConfig,
    CompactionResult,
    CompactionStrategy,
    Compactor,
    select_strategy,
)
from loop_symphony.models.finding import Finding


def make_finding(content: str, confidence: float = 0.8, source: str | None = None) -> Finding:
    """Helper to create a Finding."""
    return Finding(content=content, confidence=confidence, source=source)


class TestCompactionStrategyEnum:
    """Tests for CompactionStrategy enum."""

    def test_strategies(self):
        assert CompactionStrategy.SUMMARIZE.value == "summarize"
        assert CompactionStrategy.PRUNE.value == "prune"
        assert CompactionStrategy.SELECTIVE.value == "selective"
        assert CompactionStrategy.HYBRID.value == "hybrid"


class TestCompactionConfig:
    """Tests for CompactionConfig model."""

    def test_defaults(self):
        config = CompactionConfig()
        assert config.strategy == CompactionStrategy.HYBRID
        assert config.max_findings == 50
        assert config.min_confidence == 0.5
        assert config.chunk_size == 10

    def test_custom_config(self):
        config = CompactionConfig(
            strategy=CompactionStrategy.PRUNE,
            max_findings=20,
            min_confidence=0.7,
        )
        assert config.strategy == CompactionStrategy.PRUNE
        assert config.max_findings == 20


class TestCompactedFinding:
    """Tests for CompactedFinding model."""

    def test_basic(self):
        cf = CompactedFinding(content="Test", confidence=0.9)
        assert cf.content == "Test"
        assert cf.is_summary is False
        assert cf.original_count == 1
        assert cf.preserved is False

    def test_summary(self):
        cf = CompactedFinding(
            content="Summary of 5 findings",
            is_summary=True,
            original_count=5,
        )
        assert cf.is_summary is True
        assert cf.original_count == 5


class TestCompactionResult:
    """Tests for CompactionResult model."""

    def test_compression_ratio(self):
        result = CompactionResult(
            findings=[],
            original_count=100,
            final_count=25,
            strategy_used=CompactionStrategy.PRUNE,
        )
        assert result.compression_ratio == 0.25

    def test_compression_ratio_empty(self):
        result = CompactionResult(
            findings=[],
            original_count=0,
            final_count=0,
            strategy_used=CompactionStrategy.PRUNE,
        )
        assert result.compression_ratio == 1.0


class TestCompactorNoCompaction:
    """Tests for Compactor when no compaction needed."""

    @pytest.mark.asyncio
    async def test_no_compaction_needed(self):
        compactor = Compactor()
        findings = [make_finding(f"Finding {i}") for i in range(10)]

        result = await compactor.compact(findings)

        assert result.original_count == 10
        assert result.final_count == 10
        assert result.bytes_saved == 0

    @pytest.mark.asyncio
    async def test_empty_findings(self):
        compactor = Compactor()
        result = await compactor.compact([])

        assert result.original_count == 0
        assert result.final_count == 0


class TestCompactorPruneStrategy:
    """Tests for prune strategy."""

    @pytest.mark.asyncio
    async def test_prune_by_confidence(self):
        config = CompactionConfig(
            strategy=CompactionStrategy.PRUNE,
            max_findings=3,  # Force compaction by setting max lower than count
            min_confidence=0.6,
        )
        compactor = Compactor(config=config)

        # Need more than max_findings to trigger compaction
        findings = [
            make_finding("Low confidence", confidence=0.3),
            make_finding("High confidence", confidence=0.95),
            make_finding("Medium confidence", confidence=0.7),
            make_finding("Very low", confidence=0.2),
            make_finding("Good confidence", confidence=0.85),
            make_finding("Another low", confidence=0.4),
        ]

        result = await compactor.compact(findings)

        # Should keep only findings >= 0.6 confidence, max 3
        assert result.final_count == 3
        contents = [f.content for f in result.findings]
        assert "High confidence" in contents
        assert "Good confidence" in contents
        assert "Low confidence" not in contents

    @pytest.mark.asyncio
    async def test_prune_respects_max(self):
        config = CompactionConfig(
            strategy=CompactionStrategy.PRUNE,
            max_findings=3,
            min_confidence=0.0,
        )
        compactor = Compactor(config=config)

        findings = [make_finding(f"F{i}", confidence=0.5 + i * 0.1) for i in range(10)]

        result = await compactor.compact(findings)

        assert result.final_count == 3
        # Should keep the highest confidence ones
        assert result.findings[0].confidence >= 0.9


class TestCompactorSummarizeStrategy:
    """Tests for summarize strategy."""

    @pytest.mark.asyncio
    async def test_summarize_chunks(self):
        config = CompactionConfig(
            strategy=CompactionStrategy.SUMMARIZE,
            max_findings=5,
            chunk_size=3,
            preserve_high_confidence=False,
        )
        compactor = Compactor(config=config)

        findings = [make_finding(f"Finding number {i}") for i in range(12)]

        result = await compactor.compact(findings)

        # 12 findings / 3 chunk_size = 4 summaries
        assert result.final_count <= 5
        # At least some should be summaries (truncated without summarizer)
        summaries = [f for f in result.findings if f.is_summary]
        assert len(summaries) > 0

    @pytest.mark.asyncio
    async def test_summarize_preserves_high_confidence(self):
        config = CompactionConfig(
            strategy=CompactionStrategy.SUMMARIZE,
            max_findings=5,  # Force compaction by setting max lower than count
            chunk_size=3,
            preserve_high_confidence=True,
            high_confidence_threshold=0.9,
        )
        compactor = Compactor(config=config)

        # Need more than max_findings to trigger compaction
        findings = [
            make_finding("High 1", confidence=0.95),
            make_finding("High 2", confidence=0.92),
            make_finding("Low 1", confidence=0.5),
            make_finding("Low 2", confidence=0.4),
            make_finding("Low 3", confidence=0.3),
            make_finding("Low 4", confidence=0.35),
            make_finding("Low 5", confidence=0.45),
            make_finding("Low 6", confidence=0.25),
        ]

        result = await compactor.compact(findings)

        # High confidence should be preserved (not summarized)
        preserved = [f for f in result.findings if f.preserved]
        assert len(preserved) == 2


class TestCompactorSelectiveStrategy:
    """Tests for selective strategy."""

    @pytest.mark.asyncio
    async def test_selective_splits_by_confidence(self):
        config = CompactionConfig(
            strategy=CompactionStrategy.SELECTIVE,
            max_findings=4,  # Force compaction by setting max lower than count
            high_confidence_threshold=0.85,
        )
        compactor = Compactor(config=config)

        # Need more than max_findings to trigger compaction
        findings = [
            make_finding("High", confidence=0.9),
            make_finding("Low 1", confidence=0.5),
            make_finding("Low 2", confidence=0.4),
            make_finding("Low 3", confidence=0.3),
            make_finding("Low 4", confidence=0.2),
            make_finding("Low 5", confidence=0.35),
        ]

        result = await compactor.compact(findings)

        # High should be preserved, lows should be summarized
        assert result.final_count <= 4
        preserved = [f for f in result.findings if f.preserved]
        assert len(preserved) >= 1


class TestCompactorHybridStrategy:
    """Tests for hybrid strategy."""

    @pytest.mark.asyncio
    async def test_hybrid_high_confidence(self):
        """High confidence ratio should use prune."""
        config = CompactionConfig(
            strategy=CompactionStrategy.HYBRID,
            max_findings=3,
            high_confidence_threshold=0.85,
        )
        compactor = Compactor(config=config)

        # 80% high confidence
        findings = [
            make_finding("H1", confidence=0.95),
            make_finding("H2", confidence=0.92),
            make_finding("H3", confidence=0.88),
            make_finding("H4", confidence=0.90),
            make_finding("L1", confidence=0.5),
        ]

        result = await compactor.compact(findings)
        # Should use prune since most are high confidence
        assert result.final_count <= 3

    @pytest.mark.asyncio
    async def test_hybrid_low_confidence(self):
        """Low confidence ratio should use summarize."""
        config = CompactionConfig(
            strategy=CompactionStrategy.HYBRID,
            max_findings=3,
            high_confidence_threshold=0.85,
        )
        compactor = Compactor(config=config)

        # All low confidence
        findings = [
            make_finding("L1", confidence=0.4),
            make_finding("L2", confidence=0.3),
            make_finding("L3", confidence=0.5),
            make_finding("L4", confidence=0.4),
            make_finding("L5", confidence=0.3),
        ]

        result = await compactor.compact(findings)
        # Should have summaries
        summaries = [f for f in result.findings if f.is_summary]
        assert len(summaries) > 0


class TestSelectStrategy:
    """Tests for select_strategy function."""

    def test_empty_findings(self):
        assert select_strategy([]) == CompactionStrategy.PRUNE

    def test_research_context(self):
        findings = [make_finding("Test")]
        assert select_strategy(findings, "research") == CompactionStrategy.SUMMARIZE

    def test_fact_check_context(self):
        findings = [make_finding("Test")]
        assert select_strategy(findings, "fact_check") == CompactionStrategy.SELECTIVE

    def test_quick_context(self):
        findings = [make_finding("Test")]
        assert select_strategy(findings, "quick") == CompactionStrategy.PRUNE

    def test_high_confidence_defaults_to_prune(self):
        findings = [make_finding(f"F{i}", confidence=0.95) for i in range(10)]
        assert select_strategy(findings) == CompactionStrategy.PRUNE

    def test_low_confidence_defaults_to_summarize(self):
        findings = [make_finding(f"F{i}", confidence=0.4) for i in range(10)]
        assert select_strategy(findings) == CompactionStrategy.SUMMARIZE


class TestCompactorWithSummarizer:
    """Tests for Compactor with a mock summarizer."""

    @pytest.mark.asyncio
    async def test_uses_summarizer(self):
        """Test that summarizer is called when provided."""

        class MockSummarizer:
            def __init__(self):
                self.calls = []

            async def summarize(self, text: str) -> str:
                self.calls.append(text)
                return f"Summary of: {text[:20]}..."

        summarizer = MockSummarizer()
        config = CompactionConfig(
            strategy=CompactionStrategy.SUMMARIZE,
            max_findings=2,
            chunk_size=5,
            preserve_high_confidence=False,
        )
        compactor = Compactor(summarizer=summarizer, config=config)

        findings = [make_finding(f"Finding content {i}") for i in range(10)]

        result = await compactor.compact(findings)

        # Summarizer should have been called
        assert len(summarizer.calls) > 0
        # Results should be summaries
        assert any(f.is_summary for f in result.findings)


class TestCompactorRelevanceScoring:
    """Tests for relevance scoring."""

    def test_score_relevance_uses_confidence(self):
        compactor = Compactor()

        high = make_finding("High", confidence=0.9)
        low = make_finding("Low", confidence=0.3)

        assert compactor.score_relevance(high) == 0.9
        assert compactor.score_relevance(low) == 0.3
