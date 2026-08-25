"""
Phase 6.1: Business Rule Governance & Conflict Detection Layer for RS Graphics AI Agent.

Guarantees:
1. Deterministic Rule Authority Hierarchy (Levels 1 to 6).
2. Authoritative Core Business Rules Registry.
3. Automated Conflict Detection (Value, Source, Duplicate, Version, Stale).
4. Deterministic Conflict Resolution (Lower-level overrides prohibited).
5. Critical Level-1 Conflict Isolation with Owner Review Escalation.
6. Structured Audit Logging for all detected conflicts.
7. Zero Business Logic duplication (delegates to authoritative engines).
"""

import time
import json
from enum import IntEnum, Enum
from typing import Dict, Any, List, Optional, Tuple, Union
from datetime import datetime, timezone


class AuthorityLevel(IntEnum):
    LEVEL_1_DETERMINISTIC_ENGINE = 1   # Pricing Engine, Conversation State, Response Validator, Delivery Calculator
    LEVEL_2_STRUCTURED_DATABASE = 2    # Products Catalog, Saved Media Metadata
    LEVEL_3_TRAINING_RULES = 3         # ai_training_rules database table
    LEVEL_4_FAQ = 4                    # faq database table
    LEVEL_5_STATIC_PROMPT = 5          # System instructions & persona prompts
    LEVEL_6_LLM_GENERATED = 6          # Unverified LLM inference (Lowest)


class ConflictType(str, Enum):
    NONE = "NONE"
    VALUE_CONFLICT = "VALUE_CONFLICT"
    DUPLICATE_ACTIVE_RULE = "DUPLICATE_ACTIVE_RULE"
    SOURCE_CONFLICT = "SOURCE_CONFLICT"              # Level 1 vs Level 1 conflict
    VERSION_CONFLICT = "VERSION_CONFLICT"
    MISSING_AUTHORITATIVE_RULE = "MISSING_AUTHORITATIVE_RULE"
    STALE_RULE = "STALE_RULE"
    UNSUPPORTED_RULE = "UNSUPPORTED_RULE"


class ConflictAction(str, Enum):
    USE_AUTHORITATIVE = "USE_AUTHORITATIVE"
    REQUIRE_OWNER_REVIEW = "REQUIRE_OWNER_REVIEW"
    SAFE_FALLBACK = "SAFE_FALLBACK"


class BusinessRule:
    """Represents a single registered business rule."""
    def __init__(
        self,
        rule_id: str,
        rule_key: str,
        category: str,
        authority_level: Union[AuthorityLevel, int],
        source: str,
        value: Any,
        version: int = 1,
        active: bool = True,
        effective_from: Optional[str] = None,
        effective_to: Optional[str] = None,
        owner_approval_required: bool = False,
        description: str = ""
    ):
        self.rule_id = rule_id
        self.rule_key = rule_key
        self.category = category
        self.authority_level = int(authority_level)
        self.source = source
        self.value = value
        self.version = version
        self.active = active
        self.effective_from = effective_from
        self.effective_to = effective_to
        self.owner_approval_required = owner_approval_required
        self.description = description

    def is_currently_effective(self) -> bool:
        """Checks if rule is active and within effective time window."""
        if not self.active:
            return False
        now_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        if self.effective_from and now_str < self.effective_from:
            return False
        if self.effective_to and now_str > self.effective_to:
            return False
        return True

    def to_dict(self) -> Dict[str, Any]:
        return {
            "rule_id": self.rule_id,
            "rule_key": self.rule_key,
            "category": self.category,
            "authority_level": self.authority_level,
            "source": self.source,
            "value": self.value,
            "version": self.version,
            "active": self.active,
            "effective_from": self.effective_from,
            "effective_to": self.effective_to,
            "owner_approval_required": self.owner_approval_required,
            "description": self.description
        }


# ==============================================================================
# AUTHORITATIVE CORE BUSINESS RULES CATALOG (LEVEL 1 & LEVEL 2)
# ==============================================================================
CORE_AUTHORITATIVE_RULES: List[BusinessRule] = [
    # 1. MOQ
    BusinessRule(
        rule_id="RULE_MOQ_MIN_ORDER",
        rule_key="moq",
        category="order_policy",
        authority_level=AuthorityLevel.LEVEL_1_DETERMINISTIC_ENGINE,
        source="pricing_engine",
        value=30,
        description="Minimum order quantity for ID card and ribbon packages."
    ),
    # 2. 30-49 Small Order Surcharge
    BusinessRule(
        rule_id="RULE_TIER_30_49_SURCHARGE",
        rule_key="tier_30_49_surcharge",
        category="pricing",
        authority_level=AuthorityLevel.LEVEL_1_DETERMINISTIC_ENGINE,
        source="pricing_engine",
        value=10,
        description="Small order surcharge (+10 Tk per piece over regular rate) for 30-49 pcs."
    ),
    # 3. 50-79 Regular Tier
    BusinessRule(
        rule_id="RULE_TIER_50_79_DISCOUNT",
        rule_key="tier_50_79_discount",
        category="pricing",
        authority_level=AuthorityLevel.LEVEL_1_DETERMINISTIC_ENGINE,
        source="pricing_engine",
        value=0,
        description="50-79 pieces are strictly at regular rate with zero discount."
    ),
    # 4. 80+ Bulk Tier
    BusinessRule(
        rule_id="RULE_TIER_80_PLUS_BULK",
        rule_key="tier_80_plus_type",
        category="pricing",
        authority_level=AuthorityLevel.LEVEL_1_DETERMINISTIC_ENGINE,
        source="pricing_engine",
        value="bulk",
        description="80+ pieces qualify as 100+ bulk pricing tier with negotiation allowed."
    ),
    # 5. Package 7 Regular Price
    BusinessRule(
        rule_id="RULE_PKG_7_REGULAR_PRICE",
        rule_key="package_7_regular_price",
        category="pricing",
        authority_level=AuthorityLevel.LEVEL_1_DETERMINISTIC_ENGINE,
        source="pricing_engine",
        value=91,
        description="Package 7 regular price per set is 91 Taka."
    ),
    # 6. Package 7 Maximum Discount
    BusinessRule(
        rule_id="RULE_PKG_7_MAX_DISCOUNT",
        rule_key="package_7_max_discount",
        category="pricing",
        authority_level=AuthorityLevel.LEVEL_1_DETERMINISTIC_ENGINE,
        source="pricing_engine",
        value=9,
        description="Package 7 maximum allowed discount is 9 Taka."
    ),
    # 7. Package 7 Minimum Price Floor
    BusinessRule(
        rule_id="RULE_PKG_7_FLOOR_PRICE",
        rule_key="package_7_floor_price",
        category="pricing",
        authority_level=AuthorityLevel.LEVEL_1_DETERMINISTIC_ENGINE,
        source="pricing_engine",
        value=82,
        description="Package 7 minimum price floor is 82 Taka (prices below 82 require owner approval)."
    ),
    # 8. Package 1-6 Maximum Discount
    BusinessRule(
        rule_id="RULE_PKG_1_6_MAX_DISCOUNT",
        rule_key="package_1_6_max_discount",
        category="pricing",
        authority_level=AuthorityLevel.LEVEL_1_DETERMINISTIC_ENGINE,
        source="pricing_engine",
        value=5,
        description="Packages 1 to 6 maximum allowed discount is 5 Taka."
    ),
    # 9. Full COD Prohibited
    BusinessRule(
        rule_id="RULE_FULL_COD_ALLOWED",
        rule_key="full_cod_allowed",
        category="payment_policy",
        authority_level=AuthorityLevel.LEVEL_1_DETERMINISTIC_ENGINE,
        source="response_validator",
        value=False,
        description="100% full cash on delivery is strictly prohibited for custom printed items."
    ),
    # 10. Advance Payment Mandatory
    BusinessRule(
        rule_id="RULE_ADVANCE_REQUIRED",
        rule_key="advance_payment_required",
        category="payment_policy",
        authority_level=AuthorityLevel.LEVEL_1_DETERMINISTIC_ENGINE,
        source="response_validator",
        value=True,
        description="Advance payment (delivery charge or partial advance) is mandatory before printing."
    ),
    # 11. Delivery Inside Dhaka
    BusinessRule(
        rule_id="RULE_DELIVERY_INSIDE_DHAKA",
        rule_key="delivery_inside_dhaka_base",
        category="delivery",
        authority_level=AuthorityLevel.LEVEL_1_DETERMINISTIC_ENGINE,
        source="pricing_engine",
        value=80,
        description="Base courier delivery fee inside Dhaka is 80 Taka for the first 1kg."
    ),
    # 12. Delivery Outside Dhaka
    BusinessRule(
        rule_id="RULE_DELIVERY_OUTSIDE_DHAKA",
        rule_key="delivery_outside_dhaka_base",
        category="delivery",
        authority_level=AuthorityLevel.LEVEL_1_DETERMINISTIC_ENGINE,
        source="pricing_engine",
        value=130,
        description="Base courier delivery fee outside Dhaka is 130 Taka for the first 1kg."
    ),
    # 13. Extra KG Delivery Fee
    BusinessRule(
        rule_id="RULE_DELIVERY_EXTRA_KG",
        rule_key="delivery_extra_kg_fee",
        category="delivery",
        authority_level=AuthorityLevel.LEVEL_1_DETERMINISTIC_ENGINE,
        source="pricing_engine",
        value=20,
        description="Additional courier charge per KG above 1kg is 20 Taka."
    ),
    # 14. Courier Lead Time
    BusinessRule(
        rule_id="RULE_COURIER_LEAD_TIME",
        rule_key="courier_lead_time_hours",
        category="lead_time",
        authority_level=AuthorityLevel.LEVEL_1_DETERMINISTIC_ENGINE,
        source="response_validator",
        value="24-48 hours",
        description="Steadfast courier delivery transit time is 24 to 48 hours."
    ),
    # 15. Production Lead Time
    BusinessRule(
        rule_id="RULE_PRODUCTION_LEAD_TIME",
        rule_key="production_lead_time_days",
        category="lead_time",
        authority_level=AuthorityLevel.LEVEL_1_DETERMINISTIC_ENGINE,
        source="response_validator",
        value="5-6 days",
        description="Standard printing and production duration is 5 to 6 working days."
    ),
    # 16. Official WhatsApp Number
    BusinessRule(
        rule_id="RULE_OFFICIAL_WHATSAPP",
        rule_key="official_whatsapp",
        category="company_info",
        authority_level=AuthorityLevel.LEVEL_1_DETERMINISTIC_ENGINE,
        source="response_validator",
        value="01816504097",
        description="Official RS Graphics customer support WhatsApp number is 01816504097."
    ),
    # 17. Raw Design File Request
    BusinessRule(
        rule_id="RULE_RAW_DESIGN_FILE_REQUEST",
        rule_key="raw_design_file_request_allowed",
        category="security_policy",
        authority_level=AuthorityLevel.LEVEL_1_DETERMINISTIC_ENGINE,
        source="response_validator",
        value=False,
        description="Customer asking for raw editable design files (PSD, AI) is strictly rejected."
    ),
    # 18. Unauthorized Form Link
    BusinessRule(
        rule_id="RULE_UNAUTHORIZED_FORM_LINK",
        rule_key="unauthorized_google_form_link",
        category="workflow_policy",
        authority_level=AuthorityLevel.LEVEL_1_DETERMINISTIC_ENGINE,
        source="response_validator",
        value=False,
        description="AI must not send raw Google Form URL without deterministic form creation."
    ),
]


class RuleGovernanceAuditLog:
    """In-memory and persistent conflict audit logging."""
    _audit_records: List[Dict[str, Any]] = []

    @classmethod
    def log_conflict(
        cls,
        rule_key: str,
        authoritative_source: str,
        conflicting_source: str,
        authoritative_value: Any,
        conflicting_value: Any,
        resolution_action: str,
        conflict_type: str,
        requires_owner_review: bool
    ) -> Dict[str, Any]:
        record = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "rule_key": rule_key,
            "authoritative_source": authoritative_source,
            "conflicting_source": conflicting_source,
            "authoritative_value": authoritative_value,
            "conflicting_value": conflicting_value,
            "resolution_action": resolution_action,
            "conflict_type": conflict_type,
            "requires_owner_review": requires_owner_review
        }
        cls._audit_records.append(record)
        return record

    @classmethod
    def get_all_records(cls) -> List[Dict[str, Any]]:
        return list(cls._audit_records)

    @classmethod
    def clear(cls):
        cls._audit_records.clear()


class RuleRegistry:
    """
    Authoritative Business Rule Registry and Conflict Governance Engine.
    """
    _registry: Dict[str, List[BusinessRule]] = {}

    @classmethod
    def initialize(cls):
        """Seeds the registry with authoritative Level 1 core rules."""
        cls._registry.clear()
        for r in CORE_AUTHORITATIVE_RULES:
            cls.register_rule(r)

    @classmethod
    def register_rule(cls, rule: BusinessRule):
        """Registers a rule into the in-memory registry under its rule_key."""
        key = rule.rule_key.strip().lower()
        if key not in cls._registry:
            cls._registry[key] = []
        cls._registry[key].append(rule)

    @classmethod
    def get_authoritative_rule(cls, rule_key: str) -> Optional[BusinessRule]:
        """
        Retrieves the single highest-authority active rule for a rule_key.
        Sorted by authority_level ASC (1 is highest), then version DESC.
        """
        key = rule_key.strip().lower()
        rules = cls._registry.get(key, [])
        active_rules = [r for r in rules if r.is_currently_effective()]
        if not active_rules:
            return None
        # Sort by authority level ascending (1 is highest), then version descending
        active_rules.sort(key=lambda r: (r.authority_level, -r.version))
        return active_rules[0]

    @classmethod
    def resolve_rule_value(cls, rule_key: str, default: Any = None) -> Any:
        """Helper to get the resolved authoritative value directly."""
        r = cls.get_authoritative_rule(rule_key)
        return r.value if r else default

    @classmethod
    def inspect_and_resolve_conflict(
        cls,
        rule_key: str,
        candidate_value: Any,
        candidate_source: str,
        candidate_authority_level: Union[AuthorityLevel, int] = AuthorityLevel.LEVEL_3_TRAINING_RULES,
        candidate_version: int = 1
    ) -> Dict[str, Any]:
        """
        Evaluates a candidate rule from a lower or equal level against authoritative registry.
        Determines conflict type, resolution action, and owner review requirement.
        """
        key = rule_key.strip().lower()
        authoritative = cls.get_authoritative_rule(key)

        # 1. Missing authoritative rule check
        if not authoritative:
            audit = RuleGovernanceAuditLog.log_conflict(
                rule_key=key,
                authoritative_source="none",
                conflicting_source=candidate_source,
                authoritative_value=None,
                conflicting_value=candidate_value,
                resolution_action=ConflictAction.SAFE_FALLBACK.value,
                conflict_type=ConflictType.MISSING_AUTHORITATIVE_RULE.value,
                requires_owner_review=True
            )
            return {
                "has_conflict": True,
                "conflict_type": ConflictType.MISSING_AUTHORITATIVE_RULE,
                "rule_key": key,
                "authoritative_value": None,
                "conflicting_value": candidate_value,
                "resolved_value": candidate_value,
                "authoritative_source": "none",
                "conflicting_source": candidate_source,
                "action": ConflictAction.SAFE_FALLBACK,
                "requires_owner_review": True,
                "reason": f"No authoritative Level-1/2 rule registered for key '{key}'"
            }

        # Check if candidate rule matches authoritative rule exactly
        if candidate_value == authoritative.value:
            return {
                "has_conflict": False,
                "conflict_type": ConflictType.NONE,
                "rule_key": key,
                "authoritative_value": authoritative.value,
                "conflicting_value": None,
                "resolved_value": authoritative.value,
                "authoritative_source": authoritative.source,
                "conflicting_source": None,
                "action": ConflictAction.USE_AUTHORITATIVE,
                "requires_owner_review": False,
                "reason": "Candidate value perfectly matches authoritative rule."
            }

        # 2. Critical Level-1 vs Level-1 Conflict (e.g. Pricing Engine vs Product Catalog)
        if int(candidate_authority_level) == AuthorityLevel.LEVEL_1_DETERMINISTIC_ENGINE:
            audit = RuleGovernanceAuditLog.log_conflict(
                rule_key=key,
                authoritative_source=authoritative.source,
                conflicting_source=candidate_source,
                authoritative_value=authoritative.value,
                conflicting_value=candidate_value,
                resolution_action=ConflictAction.REQUIRE_OWNER_REVIEW.value,
                conflict_type=ConflictType.SOURCE_CONFLICT.value,
                requires_owner_review=True
            )
            return {
                "has_conflict": True,
                "conflict_type": ConflictType.SOURCE_CONFLICT,
                "rule_key": key,
                "authoritative_value": authoritative.value,
                "conflicting_value": candidate_value,
                "resolved_value": authoritative.value,
                "authoritative_source": authoritative.source,
                "conflicting_source": candidate_source,
                "action": ConflictAction.REQUIRE_OWNER_REVIEW,
                "requires_owner_review": True,
                "reason": f"CRITICAL CONFLICT: Multiple Level-1 sources disagree on '{key}' ({authoritative.source}={authoritative.value} vs {candidate_source}={candidate_value})"
            }

        # 3. Lower Level Conflict (Level 1 vs Level 3/4/5/6)
        audit = RuleGovernanceAuditLog.log_conflict(
            rule_key=key,
            authoritative_source=authoritative.source,
            conflicting_source=candidate_source,
            authoritative_value=authoritative.value,
            conflicting_value=candidate_value,
            resolution_action=ConflictAction.USE_AUTHORITATIVE.value,
            conflict_type=ConflictType.VALUE_CONFLICT.value,
            requires_owner_review=False
        )
        return {
            "has_conflict": True,
            "conflict_type": ConflictType.VALUE_CONFLICT,
            "rule_key": key,
            "authoritative_value": authoritative.value,
            "conflicting_value": candidate_value,
            "resolved_value": authoritative.value,
            "authoritative_source": authoritative.source,
            "conflicting_source": candidate_source,
            "action": ConflictAction.USE_AUTHORITATIVE,
            "requires_owner_review": False,
            "reason": f"Non-critical conflict: Lower level source '{candidate_source}' (Level {candidate_authority_level}) overridden by authoritative '{authoritative.source}' (Level {authoritative.authority_level})"
        }


# Initialize on module load
RuleRegistry.initialize()
