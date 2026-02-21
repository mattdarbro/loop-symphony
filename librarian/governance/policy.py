"""Policy engine for governance decisions."""

from enum import Enum

from pydantic import BaseModel, Field


class PolicyAction(str, Enum):
    ALLOW = "allow"
    DENY = "deny"
    REQUIRE_APPROVAL = "require_approval"


class PolicyRule(BaseModel):
    name: str
    description: str
    action_types: list[str] = Field(default_factory=list)
    min_trust_level: int = 0
    max_trust_level: int = 3
    action: PolicyAction = PolicyAction.REQUIRE_APPROVAL
    priority: int = 0


class PolicyEvaluation(BaseModel):
    action: PolicyAction
    matching_rule: str | None = None
    reason: str


class PolicyEngine:
    """Evaluates actions against policy rules."""

    def __init__(self, rules: list[PolicyRule] | None = None) -> None:
        self._rules = rules or self._default_rules()

    @staticmethod
    def _default_rules() -> list[PolicyRule]:
        """Conservative defaults for the governance layer."""
        return [
            PolicyRule(
                name="financial_data_approval",
                description="Financial data operations require human approval",
                action_types=["financial_data"],
                action=PolicyAction.REQUIRE_APPROVAL,
                priority=100,
            ),
            PolicyRule(
                name="trust_upgrade_approval",
                description="Trust level upgrades require approval",
                action_types=["trust_upgrade"],
                action=PolicyAction.REQUIRE_APPROVAL,
                priority=90,
            ),
            PolicyRule(
                name="autonomous_research",
                description="Research tasks can run autonomously at trust level 1+",
                action_types=["execute_research"],
                min_trust_level=1,
                action=PolicyAction.ALLOW,
                priority=50,
            ),
            PolicyRule(
                name="autonomous_execution",
                description="Task execution allowed at trust level 2+",
                action_types=["execute_arrangement", "execute_task"],
                min_trust_level=2,
                action=PolicyAction.ALLOW,
                priority=40,
            ),
            PolicyRule(
                name="delegating_mode",
                description="Sub-conductor management at trust level 3",
                action_types=["spawn_conductor"],
                min_trust_level=3,
                action=PolicyAction.ALLOW,
                priority=30,
            ),
        ]

    def evaluate(self, action_type: str, trust_level: int) -> PolicyEvaluation:
        """Evaluate an action against the policy rules.

        Rules are sorted by priority (highest first). The first rule whose
        ``action_types`` list contains *action_type* and whose trust-level
        range includes *trust_level* wins.  If no rule matches, the default
        is REQUIRE_APPROVAL.
        """
        sorted_rules = sorted(self._rules, key=lambda r: r.priority, reverse=True)
        for rule in sorted_rules:
            if action_type not in rule.action_types:
                continue
            if not (rule.min_trust_level <= trust_level <= rule.max_trust_level):
                continue
            return PolicyEvaluation(
                action=rule.action,
                matching_rule=rule.name,
                reason=rule.description,
            )
        return PolicyEvaluation(
            action=PolicyAction.REQUIRE_APPROVAL,
            matching_rule=None,
            reason="No matching policy rule; defaulting to require approval",
        )

    @property
    def rules(self) -> list[PolicyRule]:
        return list(self._rules)

    def add_rule(self, rule: PolicyRule) -> None:
        """Append a new policy rule."""
        self._rules.append(rule)

    def remove_rule(self, name: str) -> bool:
        """Remove a rule by name. Returns True if a rule was removed."""
        before = len(self._rules)
        self._rules = [r for r in self._rules if r.name != name]
        return len(self._rules) < before
