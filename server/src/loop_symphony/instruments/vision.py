"""Vision instrument - iterative image analysis."""

import logging
import re
import time

from loop_symphony.instruments.base import BaseInstrument, InstrumentResult
from loop_symphony.models.finding import Finding
from loop_symphony.models.outcome import Outcome
from loop_symphony.models.task import TaskContext
from loop_symphony.termination.evaluator import TerminationEvaluator
from loop_symphony.tools.claude import ClaudeClient, ImageInput

logger = logging.getLogger(__name__)

# Regex for data URI scheme: data:image/jpeg;base64,<data>
_DATA_URI_PATTERN = re.compile(
    r"^data:(image/(?:jpeg|png|gif|webp));base64,(.+)$", re.DOTALL
)

# Recognized image file extensions
_IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".gif", ".webp"}

# Extension to MIME type mapping
_EXT_TO_MEDIA_TYPE: dict[str, str] = {
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".gif": "image/gif",
    ".webp": "image/webp",
}


class VisionInstrument(BaseInstrument):
    """Vision instrument for iterative image analysis.

    Follows the scientific method adapted for vision:
    1. Define extraction goal from query
    2. Analyze image(s) with Claude vision
    3. Evaluate completeness and refine if needed

    Max 3 iterations. Terminates on confidence convergence or saturation.
    """

    name = "vision"
    max_iterations = 3
    required_capabilities = frozenset({"reasoning", "vision"})

    def __init__(self, *, claude: ClaudeClient | None = None) -> None:
        self.claude = claude if claude is not None else ClaudeClient()
        self.termination = TerminationEvaluator()

    async def execute(
        self,
        query: str,
        context: TaskContext | None = None,
    ) -> InstrumentResult:
        """Execute iterative image analysis.

        Args:
            query: The analysis query
            context: Task context containing image attachments

        Returns:
            InstrumentResult with visual analysis findings
        """
        logger.info(f"Vision instrument executing: {query[:50]}...")

        # Parse images from attachments
        images: list[ImageInput] = []
        if context and context.attachments:
            images = self.parse_attachments(context.attachments)

        if not images:
            return InstrumentResult(
                outcome=Outcome.BOUNDED,
                findings=[],
                summary="No images provided for vision analysis.",
                confidence=0.0,
                iterations=0,
                sources_consulted=[],
                suggested_followups=["Please attach an image for visual analysis."],
            )

        # State tracking
        findings: list[Finding] = []
        confidence_history: list[float] = []
        iteration = 0
        outcome = Outcome.BOUNDED
        previous_analysis: str | None = None
        checkpoint_fn = context.checkpoint_fn if context else None

        while iteration < self.max_iterations:
            iteration += 1
            iteration_start = time.time()
            logger.info(f"Vision iteration {iteration}/{self.max_iterations}")
            previous_finding_count = len(findings)

            # Build prompts
            system = self._build_system_prompt(iteration, previous_analysis)
            prompt = self._build_analysis_prompt(
                query, context, iteration, previous_analysis
            )

            # Call Claude with images
            response = await self.claude.complete_with_images(
                prompt, images, system=system
            )

            # Extract findings from response
            new_findings = self._extract_findings(response, iteration)
            findings.extend(new_findings)

            # Store analysis for next iteration's refinement context
            previous_analysis = response

            # Calculate confidence
            confidence = self.termination.calculate_confidence(
                findings,
                1,  # single source (Claude vision)
                has_answer=any(f.confidence > 0.8 for f in new_findings),
            )
            confidence_history.append(confidence)

            # Evaluate termination
            result = self.termination.evaluate(
                findings,
                iteration,
                self.max_iterations,
                confidence_history,
                previous_finding_count,
            )

            # Emit checkpoint
            if checkpoint_fn:
                iteration_ms = int((time.time() - iteration_start) * 1000)
                try:
                    await checkpoint_fn(
                        iteration,
                        "vision_analysis",
                        {"query": query, "image_count": len(images)},
                        {
                            "new_findings": len(new_findings),
                            "total_findings": len(findings),
                            "confidence": confidence,
                            "should_terminate": result.should_terminate,
                        },
                        iteration_ms,
                    )
                except Exception as e:
                    logger.warning(f"Checkpoint emission failed: {e}")

            if result.should_terminate:
                outcome = result.outcome
                logger.info(f"Terminating: {result.reason}")
                break

        # Final synthesis
        summary = await self._synthesize_analysis(query, findings)
        confidence = confidence_history[-1] if confidence_history else 0.0

        return InstrumentResult(
            outcome=outcome,
            findings=findings,
            summary=summary,
            confidence=confidence,
            iterations=iteration,
            sources_consulted=["claude_vision"],
            suggested_followups=await self._suggest_followups(
                query, findings, outcome
            ),
        )

    # ------------------------------------------------------------------
    # Attachment parsing
    # ------------------------------------------------------------------

    @staticmethod
    def parse_attachments(attachments: list[str]) -> list[ImageInput]:
        """Parse attachment strings into ImageInput objects.

        Supports:
        - Data URIs: "data:image/jpeg;base64,..."
        - HTTPS URLs: "https://example.com/photo.jpg"
          (URLs without recognized image extension default to image/jpeg)
        """
        images: list[ImageInput] = []
        for attachment in attachments:
            # Try data URI
            match = _DATA_URI_PATTERN.match(attachment)
            if match:
                images.append(ImageInput(
                    source_type="base64",
                    media_type=match.group(1),
                    data=match.group(2),
                ))
                continue

            # Try HTTPS URL
            if attachment.startswith("https://"):
                lower = attachment.lower().split("?")[0]
                media_type = "image/jpeg"  # default
                for ext, mime in _EXT_TO_MEDIA_TYPE.items():
                    if lower.endswith(ext):
                        media_type = mime
                        break
                images.append(ImageInput(
                    source_type="url",
                    media_type=media_type,
                    data=attachment,
                ))
                continue

            # Skip non-image attachments
            logger.debug(f"Skipping non-image attachment: {attachment[:50]}...")

        return images

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _build_system_prompt(
        iteration: int, previous_analysis: str | None
    ) -> str:
        """Build system prompt for image analysis."""
        base = (
            "You are a visual analysis expert. Examine the provided image(s) "
            "carefully and extract all relevant information related to the "
            "user's query.\n\n"
            "Respond with a JSON object (no markdown wrapping) with these keys:\n"
            '- "observations": list of specific things you see that are relevant\n'
            '- "analysis": narrative interpretation addressing the query\n'
            '- "confidence": 0.0-1.0 how confident you are in your analysis'
        )

        if iteration > 1 and previous_analysis:
            base += (
                "\n\nYou previously analyzed this image. Look again more "
                "carefully, focusing on details you might have missed, "
                "ambiguities, or areas where confidence was low. Add new "
                "observations and correct any mistakes."
            )

        return base

    @staticmethod
    def _build_analysis_prompt(
        query: str,
        context: TaskContext | None,
        iteration: int,
        previous_analysis: str | None,
    ) -> str:
        """Build the user prompt for image analysis."""
        prompt = f"Query: {query}"

        if context:
            if context.location:
                prompt += f"\nUser location: {context.location}"

        if iteration > 1 and previous_analysis:
            prompt += (
                f"\n\nPrevious analysis (iteration {iteration - 1}):\n"
                f"{previous_analysis[:2000]}"
            )

        prompt += "\n\nAnalyze the image(s) and respond with the JSON object."
        return prompt

    def _extract_findings(
        self, response: str, iteration: int
    ) -> list[Finding]:
        """Extract structured findings from Claude's response."""
        parsed = ClaudeClient._parse_json_response(response)

        if parsed and "observations" in parsed:
            observations = parsed["observations"]
            response_confidence = float(parsed.get("confidence", 0.7))
            findings = []
            for obs in observations:
                if isinstance(obs, str) and obs.strip():
                    findings.append(Finding(
                        content=obs,
                        source="claude_vision",
                        confidence=response_confidence,
                    ))
            if findings:
                return findings

        # Fallback: treat entire response as single finding
        return [Finding(
            content=response[:1000],
            source="claude_vision",
            confidence=0.7,
        )]

    async def _synthesize_analysis(
        self, query: str, findings: list[Finding]
    ) -> str:
        """Synthesize all findings into a coherent summary."""
        if not findings:
            return "No visual information could be extracted."

        findings_text = "\n".join(
            f"- {f.content}" for f in findings
        )

        prompt = f"""Original query: {query}

Visual observations:
{findings_text}

Synthesize these observations into a clear, direct answer to the query."""

        system = (
            "You are a visual analysis synthesizer. Combine the observations "
            "into a coherent summary that directly addresses the user's query. "
            "Be concise but comprehensive."
        )

        try:
            return await self.claude.complete(prompt, system=system)
        except Exception as e:
            logger.warning(f"Synthesis failed: {e}")
            return findings[0].content

    async def _suggest_followups(
        self,
        query: str,
        findings: list[Finding],
        outcome: Outcome,
    ) -> list[str]:
        """Generate suggested follow-up questions."""
        if not findings:
            return []

        findings_summary = "\n".join(f.content[:100] for f in findings[:5])

        system = (
            "Based on the visual analysis, suggest 1-2 follow-up questions "
            "the user might want to explore about the image(s)."
        )

        prompt = f"""Original query: {query}
Analysis outcome: {outcome.value}

Key observations:
{findings_summary}

Suggest 1-2 follow-up questions. Return ONLY the questions, one per line."""

        try:
            response = await self.claude.complete(prompt, system=system)
            questions = [
                q.strip() for q in response.strip().split("\n") if q.strip()
            ]
            return questions[:2]
        except Exception:
            return []
