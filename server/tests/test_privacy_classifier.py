"""Tests for server-side privacy classifier (Phase 4C)."""

import pytest

from loop_symphony.privacy.classifier import (
    PrivacyAssessment,
    PrivacyCategory,
    PrivacyClassifier,
    PrivacyLevel,
)


class TestPrivacyModels:
    """Tests for privacy data models."""

    def test_privacy_assessment_defaults(self):
        assessment = PrivacyAssessment()
        assert assessment.level == PrivacyLevel.PUBLIC
        assert assessment.categories == []
        assert assessment.confidence == 0.5
        assert assessment.should_stay_local is False

    def test_privacy_level_values(self):
        assert PrivacyLevel.PUBLIC == "public"
        assert PrivacyLevel.SENSITIVE == "sensitive"
        assert PrivacyLevel.PRIVATE == "private"
        assert PrivacyLevel.CONFIDENTIAL == "confidential"

    def test_privacy_category_values(self):
        assert PrivacyCategory.HEALTH == "health"
        assert PrivacyCategory.FINANCIAL == "financial"
        assert PrivacyCategory.IDENTITY == "identity"
        assert PrivacyCategory.NONE == "none"


class TestPrivacyClassifier:
    """Tests for PrivacyClassifier classification logic."""

    def test_public_query(self):
        classifier = PrivacyClassifier()
        result = classifier.classify("What is the capital of France?")
        assert result.level == PrivacyLevel.PUBLIC
        assert PrivacyCategory.NONE in result.categories
        assert result.should_stay_local is False

    def test_health_query_is_private(self):
        classifier = PrivacyClassifier()
        result = classifier.classify("What are the symptoms of my medication side effects?")
        assert result.level == PrivacyLevel.PRIVATE
        assert PrivacyCategory.HEALTH in result.categories
        assert result.should_stay_local is True

    def test_financial_query_is_private(self):
        classifier = PrivacyClassifier()
        result = classifier.classify("How much do I make per year? My salary is $150000")
        assert result.level == PrivacyLevel.PRIVATE
        assert PrivacyCategory.FINANCIAL in result.categories
        assert result.should_stay_local is True

    def test_identity_query_is_confidential(self):
        classifier = PrivacyClassifier()
        result = classifier.classify("My SSN is 123-45-6789")
        assert result.level == PrivacyLevel.CONFIDENTIAL
        assert PrivacyCategory.IDENTITY in result.categories
        assert result.should_stay_local is True

    def test_personal_query_is_sensitive(self):
        classifier = PrivacyClassifier()
        result = classifier.classify("I feel really sad about my relationship")
        assert result.level == PrivacyLevel.SENSITIVE
        assert PrivacyCategory.PERSONAL in result.categories
        assert result.should_stay_local is False  # Sensitive != must stay local

    def test_location_query_is_sensitive(self):
        classifier = PrivacyClassifier()
        result = classifier.classify("Where do I live? My home address is...")
        assert result.level == PrivacyLevel.SENSITIVE
        assert PrivacyCategory.LOCATION in result.categories

    def test_work_query_is_sensitive(self):
        classifier = PrivacyClassifier()
        result = classifier.classify("This is confidential company information")
        assert result.level == PrivacyLevel.SENSITIVE
        assert PrivacyCategory.WORK in result.categories

    def test_legal_query_is_private(self):
        classifier = PrivacyClassifier()
        result = classifier.classify("My lawyer said I should sue")
        assert result.level == PrivacyLevel.PRIVATE
        assert PrivacyCategory.LEGAL in result.categories
        assert result.should_stay_local is True

    def test_multiple_categories_detected(self):
        classifier = PrivacyClassifier()
        result = classifier.classify(
            "My doctor said my salary isn't enough for the surgery"
        )
        assert PrivacyCategory.HEALTH in result.categories
        assert PrivacyCategory.FINANCIAL in result.categories
        assert result.level == PrivacyLevel.PRIVATE  # Highest of HEALTH + FINANCIAL

    def test_confidence_increases_with_matches(self):
        classifier = PrivacyClassifier()
        # Fewer category matches
        result1 = classifier.classify("I have a headache")
        # More category matches (health + financial + personal)
        result2 = classifier.classify(
            "My doctor says my salary stress is causing anxiety and I feel sad"
        )
        assert result2.confidence > result1.confidence


class TestPrivacyClassifierStrictMode:
    """Tests for strict mode behavior."""

    def test_strict_mode_forces_local_for_sensitive(self):
        classifier = PrivacyClassifier(strict_mode=True)
        result = classifier.classify("I feel really sad about my relationship")
        assert result.level == PrivacyLevel.SENSITIVE
        assert result.should_stay_local is True  # Strict mode!

    def test_non_strict_mode_allows_sensitive_server(self):
        classifier = PrivacyClassifier(strict_mode=False)
        result = classifier.classify("I feel really sad about my relationship")
        assert result.level == PrivacyLevel.SENSITIVE
        assert result.should_stay_local is False  # Non-strict allows server


class TestPrivacyClassifierHelpers:
    """Tests for convenience methods."""

    def test_is_sensitive_true(self):
        classifier = PrivacyClassifier()
        assert classifier.is_sensitive("My doctor prescribed medication") is True

    def test_is_sensitive_false(self):
        classifier = PrivacyClassifier()
        assert classifier.is_sensitive("What is the capital of France?") is False

    def test_must_stay_local_true(self):
        classifier = PrivacyClassifier()
        assert classifier.must_stay_local("My SSN is 123-45-6789") is True

    def test_must_stay_local_false_for_public(self):
        classifier = PrivacyClassifier()
        assert classifier.must_stay_local("What is Python?") is False

    def test_must_stay_local_false_for_sensitive(self):
        classifier = PrivacyClassifier()
        # Sensitive but not must-stay-local in non-strict mode
        assert classifier.must_stay_local("I feel sad") is False
