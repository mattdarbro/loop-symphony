"""Note instrument - atomic, single-cycle execution."""

import logging

from loop_library.instruments.base import BaseInstrument, InstrumentResult
from loop_library.models.finding import Finding
from loop_library.models.outcome import Outcome
from loop_library.models.task import TaskContext
from loop_library.tools.claude import ClaudeClient

logger = logging.getLogger(__name__)


class NoteInstrument(BaseInstrument):
    """Note instrument for simple, atomic queries.

    Single Claude API call, no iteration, no web search.
    """

    name = "note"
    max_iterations = 1
    required_capabilities = frozenset({"reasoning"})

    def __init__(self, *, claude: ClaudeClient | None = None) -> None:
        self.claude = claude if claude is not None else ClaudeClient()

    async def execute(
        self,
        query: str,
        context: TaskContext | None = None,
    ) -> InstrumentResult:
        logger.info(f"Note instrument executing: {query[:50]}...")

        system = self._build_system_prompt(context)
        prompt = self._build_prompt(query, context)
        response = await self.claude.complete(prompt, system=system)

        finding = Finding(
            content=response,
            source="claude",
            confidence=0.9,
        )

        return InstrumentResult(
            outcome=Outcome.COMPLETE,
            findings=[finding],
            summary=response,
            confidence=0.9,
            iterations=1,
            sources_consulted=["claude"],
        )

    def _build_system_prompt(self, context: TaskContext | None) -> str:
        base = (
            "You are a helpful assistant that provides clear, accurate, and concise answers. "
            "Be direct and informative. If you're unsure about something, say so."
        )
        if context and context.conversation_summary:
            base += f"\n\nConversation context: {context.conversation_summary}"

        # Use investigation brief to enrich the system prompt
        if context and context.investigation_brief:
            brief = context.investigation_brief
            if brief.get("intent"):
                base += f"\n\nFrame your answer around this decision context: {brief['intent']}"
            if brief.get("exclusions"):
                base += f"\n\nDo NOT cover: {brief['exclusions']}"
            if brief.get("precision"):
                base += f"\n\nPrecision requirement: {brief['precision']}"

        return base

    def _build_prompt(self, query: str, context: TaskContext | None) -> str:
        prompt = query
        additions = []

        if context:
            if context.location:
                additions.append(f"User location: {context.location}")
            if context.attachments:
                additions.append(f"Attachments: {len(context.attachments)} provided")

            # Add brief context to the prompt
            if context.investigation_brief:
                brief = context.investigation_brief
                if brief.get("context"):
                    additions.append(f"Background: {brief['context']}")
                if brief.get("proposed_approach"):
                    additions.append(f"User's suggested approach: {brief['proposed_approach']}")
                if brief.get("tools_and_data"):
                    additions.append(f"Relevant tools/data: {brief['tools_and_data']}")

        if additions:
            prompt = f"{query}\n\n[Context: {'; '.join(additions)}]"
        return prompt
