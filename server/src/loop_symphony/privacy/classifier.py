"""Privacy classification for routing decisions (Phase 4C).

Server-side port of local_room/privacy.py. Detects privacy-sensitive
queries so the Conductor can route them to local rooms.
"""

import re
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class PrivacyCategory(str, Enum):
    """Categories of privacy-sensitive content."""

    HEALTH = "health"          # Medical, symptoms, medications
    FINANCIAL = "financial"    # Banking, income, spending
    PERSONAL = "personal"      # Relationships, emotions, diary
    LOCATION = "location"      # Where I am, where I've been
    IDENTITY = "identity"      # SSN, passwords, credentials
    WORK = "work"              # Confidential work matters
    LEGAL = "legal"            # Legal issues, disputes
    NONE = "none"              # Not privacy-sensitive


class PrivacyLevel(str, Enum):
    """How sensitive is this content?"""

    PUBLIC = "public"          # Fine to send anywhere
    SENSITIVE = "sensitive"    # Prefer local, but server OK if needed
    PRIVATE = "private"        # Must stay local
    CONFIDENTIAL = "confidential"  # Never leave device


class PrivacyAssessment(BaseModel):
    """Result of privacy classification."""

    level: PrivacyLevel = PrivacyLevel.PUBLIC
    categories: list[PrivacyCategory] = Field(default_factory=list)
    confidence: float = Field(default=0.5, ge=0.0, le=1.0)
    should_stay_local: bool = False
    reason: str | None = None


# Keywords that indicate privacy-sensitive content
PRIVACY_PATTERNS: dict[PrivacyCategory, list[str]] = {
    PrivacyCategory.HEALTH: [
        r"\b(symptom|diagnosis|medication|prescription|doctor|hospital|medical|health|illness|disease|pain|anxiety|depression|therapy|therapist|psychiatrist|mental health|blood pressure|heart rate|weight|bmi|pregnant|pregnancy|std|hiv|cancer|diabetes|allergy|vaccine|surgery)\b",
        r"\b(headache|fever|cough|nausea|insomnia|fatigue)\b",
        r"\b(my doctor|my therapist|my medication|my prescription)\b",
    ],
    PrivacyCategory.FINANCIAL: [
        r"\b(salary|income|tax|bank|account|credit card|debit|loan|mortgage|debt|investment|portfolio|net worth|savings|budget|spending)\b",
        r"\b(how much (do i|i) (make|earn|owe|spend))\b",
        r"\b(my bank|my account|my credit|my salary)\b",
        r"\$\d+",  # Dollar amounts
    ],
    PrivacyCategory.PERSONAL: [
        r"\b(relationship|boyfriend|girlfriend|spouse|husband|wife|partner|divorce|breakup|dating|marriage|family|argument|fight|feeling|emotion|sad|happy|angry|frustrated|lonely|love|hate)\b",
        r"\b(my (boyfriend|girlfriend|spouse|husband|wife|partner|ex))\b",
        r"\b(i feel|i'm feeling|i am feeling)\b",
        r"\b(diary|journal|secret|private|personal)\b",
    ],
    PrivacyCategory.LOCATION: [
        r"\b(my (home|house|apartment|address|location|whereabouts))\b",
        r"\b(where (do i|i) live)\b",
        r"\b(i('m| am) at|i was at|i went to)\b",
        r"\b(track|tracking|gps|geolocation)\b",
    ],
    PrivacyCategory.IDENTITY: [
        r"\b(ssn|social security|passport|driver'?s? license|id number|pin|password|credential|login)\b",
        r"\b(my (ssn|password|pin|username))\b",
        r"\b\d{3}-\d{2}-\d{4}\b",  # SSN pattern
    ],
    PrivacyCategory.WORK: [
        r"\b(confidential|proprietary|trade secret|nda|non-disclosure|classified|internal only)\b",
        r"\b(my (company|employer|boss|coworker|colleague))\b",
        r"\b(work (problem|issue|conflict))\b",
    ],
    PrivacyCategory.LEGAL: [
        r"\b(lawyer|attorney|lawsuit|sue|court|legal|arrest|police|crime|criminal)\b",
        r"\b(my lawyer|my attorney|my case)\b",
    ],
}

# Map categories to privacy levels
CATEGORY_LEVELS: dict[PrivacyCategory, PrivacyLevel] = {
    PrivacyCategory.HEALTH: PrivacyLevel.PRIVATE,
    PrivacyCategory.FINANCIAL: PrivacyLevel.PRIVATE,
    PrivacyCategory.PERSONAL: PrivacyLevel.SENSITIVE,
    PrivacyCategory.LOCATION: PrivacyLevel.SENSITIVE,
    PrivacyCategory.IDENTITY: PrivacyLevel.CONFIDENTIAL,
    PrivacyCategory.WORK: PrivacyLevel.SENSITIVE,
    PrivacyCategory.LEGAL: PrivacyLevel.PRIVATE,
    PrivacyCategory.NONE: PrivacyLevel.PUBLIC,
}


class PrivacyClassifier:
    """Classifies queries for privacy sensitivity.

    Uses keyword matching and patterns to detect privacy-sensitive content.
    """

    def __init__(self, strict_mode: bool = False) -> None:
        """Initialize the classifier.

        Args:
            strict_mode: If True, any hint of privacy = stay local
        """
        self._strict_mode = strict_mode
        self._compiled_patterns: dict[PrivacyCategory, list[re.Pattern]] = {}

        # Pre-compile regex patterns
        for category, patterns in PRIVACY_PATTERNS.items():
            self._compiled_patterns[category] = [
                re.compile(p, re.IGNORECASE) for p in patterns
            ]

    def classify(self, query: str, context: dict[str, Any] | None = None) -> PrivacyAssessment:
        """Classify a query for privacy sensitivity.

        Args:
            query: The query to classify
            context: Optional context (may contain additional signals)

        Returns:
            PrivacyAssessment with level, categories, and routing recommendation
        """
        detected_categories: list[PrivacyCategory] = []
        match_counts: dict[PrivacyCategory, int] = {}

        # Check each category's patterns
        for category, patterns in self._compiled_patterns.items():
            matches = 0
            for pattern in patterns:
                if pattern.search(query):
                    matches += 1

            if matches > 0:
                detected_categories.append(category)
                match_counts[category] = matches

        # No matches = public
        if not detected_categories:
            return PrivacyAssessment(
                level=PrivacyLevel.PUBLIC,
                categories=[PrivacyCategory.NONE],
                confidence=0.8,
                should_stay_local=False,
                reason="No privacy-sensitive content detected",
            )

        # Determine highest privacy level
        highest_level = PrivacyLevel.PUBLIC
        for category in detected_categories:
            cat_level = CATEGORY_LEVELS[category]
            if self._level_rank(cat_level) > self._level_rank(highest_level):
                highest_level = cat_level

        # Calculate confidence based on match count
        total_matches = sum(match_counts.values())
        confidence = min(0.95, 0.5 + (total_matches * 0.1))

        # Determine if should stay local
        should_stay_local = (
            highest_level in (PrivacyLevel.PRIVATE, PrivacyLevel.CONFIDENTIAL)
            or (self._strict_mode and highest_level == PrivacyLevel.SENSITIVE)
        )

        # Build reason
        cat_names = [c.value for c in detected_categories]
        reason = f"Detected privacy categories: {', '.join(cat_names)}"

        return PrivacyAssessment(
            level=highest_level,
            categories=detected_categories,
            confidence=confidence,
            should_stay_local=should_stay_local,
            reason=reason,
        )

    def _level_rank(self, level: PrivacyLevel) -> int:
        """Get numeric rank for privacy level comparison."""
        ranks = {
            PrivacyLevel.PUBLIC: 0,
            PrivacyLevel.SENSITIVE: 1,
            PrivacyLevel.PRIVATE: 2,
            PrivacyLevel.CONFIDENTIAL: 3,
        }
        return ranks.get(level, 0)

    def is_sensitive(self, query: str) -> bool:
        """Quick check if query is privacy-sensitive."""
        assessment = self.classify(query)
        return assessment.level != PrivacyLevel.PUBLIC

    def must_stay_local(self, query: str) -> bool:
        """Check if query must absolutely stay local."""
        assessment = self.classify(query)
        return assessment.should_stay_local
