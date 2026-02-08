"""Knowledge seed data (Phase 5A).

Static baseline content for the five knowledge files. Seeded once on
first initialization; tracker-derived entries are added later via refresh.
"""

import logging
from typing import Any

from loop_symphony.models.knowledge import KnowledgeCategory, KnowledgeSource

logger = logging.getLogger(__name__)


CAPABILITIES_SEED: list[dict[str, Any]] = [
    {
        "title": "Cognitive Loop Processing",
        "content": (
            "Processes queries through iterative cognitive loops: "
            "problem framing, hypothesis generation, testing, analysis, "
            "and reflection. Each iteration refines understanding until "
            "confidence thresholds are met or saturation is detected."
        ),
        "tags": ["core", "reasoning"],
    },
    {
        "title": "Multi-Room Architecture",
        "content": (
            "Routes tasks across Server, Local (Ollama), and iOS rooms "
            "based on capabilities, privacy requirements, and room health. "
            "Server handles complex reasoning and web search; Local handles "
            "privacy-sensitive tasks offline; iOS provides the user interface."
        ),
        "tags": ["rooms", "routing"],
    },
    {
        "title": "Arrangement Composition",
        "content": (
            "Composes complex workflows from simple instruments: sequential "
            "chains (A then B), parallel branches (A and B simultaneously), "
            "and cross-room compositions (split across rooms, merge results). "
            "Novel arrangements are proposed by the planner and can be saved "
            "for reuse when they perform well."
        ),
        "tags": ["composition", "arrangements"],
    },
    {
        "title": "Error Pattern Learning",
        "content": (
            "Tracks errors with rich context (category, instrument, tool, query) "
            "and detects recurring patterns. Provides suggested adjustments based "
            "on learned patterns to avoid repeating mistakes."
        ),
        "tags": ["learning", "errors"],
    },
    {
        "title": "Privacy-Aware Routing",
        "content": (
            "Classifies query privacy across 7 categories (health, financial, "
            "personal, location, identity, work, legal) with 4 levels (public, "
            "sensitive, private, confidential). Private/confidential queries "
            "route to Local Room for offline processing."
        ),
        "tags": ["privacy", "routing"],
    },
    {
        "title": "Web Search Integration",
        "content": (
            "Research instrument uses web search (Tavily) for current information. "
            "Supports parallel search queries with result synthesis. "
            "Available only in Server room."
        ),
        "tags": ["search", "research"],
    },
    {
        "title": "Trust Escalation",
        "content": (
            "Tracks per-user success rates and manages trust levels. "
            "New users start at trust level 0 (requires approval). "
            "Consistent success earns higher autonomy levels."
        ),
        "tags": ["trust", "users"],
    },
    {
        "title": "Heartbeat Scheduling",
        "content": (
            "Scheduled recurring tasks via heartbeat system. "
            "Supports cron-like scheduling with automatic execution "
            "and configurable notification on completion."
        ),
        "tags": ["scheduling", "heartbeats"],
    },
    {
        "title": "Notification Channels",
        "content": (
            "Sends notifications via Telegram, webhooks, and push (APNs). "
            "Configurable per-user preferences with priority levels "
            "and quiet hours support."
        ),
        "tags": ["notifications"],
    },
]


BOUNDARIES_SEED: list[dict[str, Any]] = [
    {
        "title": "No Real-Time Data Streams",
        "content": (
            "Cannot maintain persistent connections to real-time data feeds. "
            "Web search provides near-real-time information but with inherent "
            "latency. For time-critical data, consider heartbeat-based polling."
        ),
        "tags": ["limitation", "data"],
    },
    {
        "title": "No Code Execution",
        "content": (
            "Cannot execute arbitrary code, scripts, or shell commands. "
            "All processing is through structured cognitive loops and "
            "registered instruments."
        ),
        "tags": ["limitation", "security"],
    },
    {
        "title": "Single-User Sessions",
        "content": (
            "Each task request is processed independently. "
            "No shared state between concurrent users beyond "
            "global knowledge and saved arrangements."
        ),
        "tags": ["limitation", "concurrency"],
    },
    {
        "title": "Local Room Requires Ollama",
        "content": (
            "Local Room processing requires a running Ollama instance. "
            "When Ollama is unavailable, tasks fall back to Server room "
            "with potential privacy implications."
        ),
        "tags": ["limitation", "local"],
    },
    {
        "title": "Context Window Limits",
        "content": (
            "Long-running tasks may hit context window limits. "
            "Compaction strategies (summarization, pruning, selective) "
            "manage this automatically, but very large result sets "
            "may lose detail through summarization."
        ),
        "tags": ["limitation", "context"],
    },
    {
        "title": "No File System Access",
        "content": (
            "Cannot read or write files directly. "
            "All data persistence is through the database layer. "
            "File-based operations require external integration."
        ),
        "tags": ["limitation", "files"],
    },
]


PATTERNS_SEED: list[dict[str, Any]] = [
    {
        "title": "Research-Synthesis Flow",
        "content": (
            "For complex questions: use Research instrument to gather "
            "information via web search, then Synthesis instrument to "
            "merge and reconcile findings. This sequential composition "
            "produces well-sourced, comprehensive answers."
        ),
        "tags": ["workflow", "research"],
    },
    {
        "title": "Iterative Refinement",
        "content": (
            "When initial confidence is low, the cognitive loop iterates: "
            "each cycle narrows hypotheses based on test results. "
            "Typically converges within 2-4 iterations for factual queries."
        ),
        "tags": ["workflow", "iteration"],
    },
    {
        "title": "Privacy-First Routing",
        "content": (
            "Queries containing health, financial, or identity data are "
            "automatically routed to the Local Room for offline processing. "
            "Users can trust that sensitive data stays on-device when "
            "the Local Room is available."
        ),
        "tags": ["privacy", "routing"],
    },
    {
        "title": "Graceful Degradation",
        "content": (
            "When rooms go offline, tasks automatically fall back to "
            "available rooms. Failover events are tracked in metadata "
            "for transparency. The Server room is always the last resort."
        ),
        "tags": ["reliability", "fallback"],
    },
]


CHANGELOG_SEED: list[dict[str, Any]] = [
    {
        "title": "Phase 4: Local Room & Cross-Room Routing",
        "content": (
            "Added Local Room with Ollama integration for offline processing. "
            "Privacy-aware routing classifies queries and routes sensitive data "
            "to Local Room. Cross-room composition enables parallel execution "
            "across rooms. Graceful degradation handles room failures."
        ),
        "tags": ["release", "phase-4"],
    },
    {
        "title": "Phase 3: Autonomy Layer",
        "content": (
            "Added novel arrangement planning, loop proposals, meta-learning "
            "(arrangement tracking and saving), autonomic/semi-autonomic process "
            "types, background task management, context compaction, error learning, "
            "and notification system."
        ),
        "tags": ["release", "phase-3"],
    },
    {
        "title": "Phase 2: Intelligence Layer",
        "content": (
            "Added synthesis instrument, vision instrument, analyze-and-route "
            "conductor, sequential and parallel compositions, process types, "
            "checkpoint system, trust escalation, and intent classification."
        ),
        "tags": ["release", "phase-2"],
    },
    {
        "title": "Phase 1: Foundation",
        "content": (
            "Core framework: FastAPI server, cognitive loop engine, "
            "note and research instruments, four-state outcomes, "
            "tool protocol with registry, Supabase persistence."
        ),
        "tags": ["release", "phase-1"],
    },
]


async def seed_knowledge(db: "DatabaseClient") -> int:
    """Seed baseline knowledge entries if not already present.

    Idempotent: only inserts entries if no SEED entries exist
    for a given category.

    Args:
        db: The database client

    Returns:
        Number of entries created
    """
    from loop_symphony.db.client import DatabaseClient

    total_created = 0

    category_seeds: dict[str, list[dict[str, Any]]] = {
        KnowledgeCategory.CAPABILITIES.value: CAPABILITIES_SEED,
        KnowledgeCategory.BOUNDARIES.value: BOUNDARIES_SEED,
        KnowledgeCategory.PATTERNS.value: PATTERNS_SEED,
        KnowledgeCategory.CHANGELOG.value: CHANGELOG_SEED,
    }

    for category_value, seeds in category_seeds.items():
        # Check if seed entries already exist for this category
        existing = await db.list_knowledge_entries(
            category=category_value,
            source=KnowledgeSource.SEED.value,
        )
        if existing:
            logger.debug(
                f"Seed entries already exist for {category_value} "
                f"({len(existing)} entries), skipping"
            )
            continue

        # Insert seed entries
        for seed in seeds:
            entry_data = {
                "category": category_value,
                "title": seed["title"],
                "content": seed["content"],
                "source": KnowledgeSource.SEED.value,
                "confidence": 1.0,
                "tags": seed.get("tags", []),
            }
            await db.create_knowledge_entry(entry_data)
            total_created += 1

        logger.info(
            f"Seeded {len(seeds)} entries for {category_value}"
        )

    return total_created
