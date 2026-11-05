"""Category groups and their built-in (system) values.

Code refers to system values by `system_key`, never by display name, so admins may rename them.
"""

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

# Config value types accepted per key.
BOOL, STR, STR_LIST, UUID_STR = "bool", "str", "str_list", "uuid"

OTHER = "other"


@dataclass(frozen=True)
class SystemValue:
    key: str
    name: str
    config: dict[str, Any] = field(default_factory=dict)
    # Protected values cannot be deactivated because business logic depends on them.
    protected: bool = False


@dataclass(frozen=True)
class CategoryGroup:
    key: str
    label: str
    domain: str  # finance | people | delivery | general  -> permission categories.manage.<domain>
    description: str
    config_schema: dict[str, str]
    values: tuple[SystemValue, ...]
    # Allowed values (value -> label) for settings that are a fixed list.
    config_choices: dict[str, dict[str, str]] = field(default_factory=dict)
    # Settings the code relies on: fixed on built-in values, editable on custom ones.
    system_locked: tuple[str, ...] = ()
    # Cross-field rule: returns [(key, message)] for an invalid combination.
    config_check: Callable[[dict[str, Any]], list[tuple[str, str]]] | None = None

    @property
    def permission(self) -> str:
        return f"categories.manage.{self.domain}"


def _other(**config: Any) -> SystemValue:
    return SystemValue(OTHER, "Other", config, protected=True)


# Payment purposes: which ledger posting a payment gets (docs/architecture.md, Section 7.3).
DIRECTIONS = {"receive": "Money in", "pay": "Money out", "internal_transfer": "Between our own accounts"}
POSTING_RULES = {
    "R1": "Customer / project payment (split between employees)",
    "R2": "Other income",
    "R3": "Owner capital",
    "P1": "Supplier / operating expense",
    "P2": "Employee salary",
    "P3": "Owner drawings",
    "P4": "Hired manager payment",
    "T1": "Transfer between our accounts",
}
RULE_DIRECTION = {"R": "receive", "P": "pay", "T": "internal_transfer"}

ACCOUNT_KINDS = {"bank": "Bank account", "cash": "Cash", "crypto_wallet": "Crypto wallet", "credit_card": "Credit card"}
# Payment Entry fields a category can make mandatory (checked when the payment is previewed or submitted).
REQUIRABLE_FIELDS = {
    "party_id": "Party (customer / supplier)",
    "project_id": "Project",
    "reference_no": "Reference number",
    "description": "Description",
}
COLORS = {
    c: c.capitalize()
    for c in ("slate", "red", "orange", "amber", "yellow", "green", "teal", "blue", "indigo", "violet", "pink")
}


def _check_purpose(config: dict[str, Any]) -> list[tuple[str, str]]:
    rule, direction = config.get("posting_rule"), config.get("direction")
    if rule and direction and RULE_DIRECTION[rule[0]] != direction:
        return [("config.posting_rule", f"“{POSTING_RULES[rule]}” doesn't fit {DIRECTIONS[direction].lower()}")]
    if config.get("requires_attribution") and rule and rule != "R1":
        return [("config.requires_attribution", "Only customer / project payments are split between employees")]
    return []


GROUPS: dict[str, CategoryGroup] = {
    g.key: g
    for g in [
        CategoryGroup(
            "payment_method",
            "Payment methods",
            "finance",
            "How money moved (bank transfer, card, crypto, ...).",
            {"allowed_payment_account_kinds": STR_LIST, "requires_reference_no": BOOL},
            (
                SystemValue("bank_transfer", "Bank Transfer", {"allowed_payment_account_kinds": ["bank"]}),
                SystemValue("credit_card", "Credit Card", {"allowed_payment_account_kinds": ["credit_card", "bank"]}),
                SystemValue("crypto_transfer", "Crypto Transfer", {"allowed_payment_account_kinds": ["crypto_wallet"]}),
                SystemValue("cash", "Cash", {"allowed_payment_account_kinds": ["cash"]}),
                _other(),
            ),
            config_choices={"allowed_payment_account_kinds": ACCOUNT_KINDS},
        ),
        CategoryGroup(
            "payment_purpose",
            "Payment purposes",
            "finance",
            "Why a payment happened. Drives the posting rule and whether employee attribution is required.",
            {"direction": STR, "posting_rule": STR, "default_account_id": UUID_STR, "requires_attribution": BOOL},
            (
                SystemValue(
                    "project_payment",
                    "Project / Customer Payment",
                    {"direction": "receive", "posting_rule": "R1", "requires_attribution": True},
                    True,
                ),
                SystemValue("other_income", "Other Income", {"direction": "receive", "posting_rule": "R2"}, True),
                SystemValue("owner_capital", "Owner Capital", {"direction": "receive", "posting_rule": "R3"}, True),
                SystemValue(
                    "operating_expense",
                    "Supplier / Operating Expense",
                    {"direction": "pay", "posting_rule": "P1"},
                    True,
                ),
                SystemValue("employee_salary", "Employee Salary", {"direction": "pay", "posting_rule": "P2"}, True),
                SystemValue("hire_payment", "Hired Manager Payment", {"direction": "pay", "posting_rule": "P4"}, True),
                SystemValue("owner_drawings", "Owner Drawings", {"direction": "pay", "posting_rule": "P3"}, True),
                SystemValue(
                    "internal_transfer",
                    "Internal Transfer",
                    {"direction": "internal_transfer", "posting_rule": "T1"},
                    True,
                ),
                _other(),
            ),
            config_choices={"direction": DIRECTIONS, "posting_rule": POSTING_RULES},
            system_locked=("direction", "posting_rule", "requires_attribution"),
            config_check=_check_purpose,
        ),
        CategoryGroup(
            "party_subtype",
            "Party subtypes",
            "finance",
            "Kinds of 'Other' parties (partner, affiliate, ...).",
            {},
            (
                SystemValue("partner", "Partner"),
                SystemValue("affiliate", "Affiliate"),
                SystemValue("contractor", "Contractor"),
                _other(),
            ),
        ),
        CategoryGroup(
            "income_category",
            "Income categories",
            "finance",
            "Classification of income; maps to an income account.",
            {"default_account_id": UUID_STR, "required_fields": STR_LIST},
            (
                SystemValue("software_development", "Software Development"),
                SystemValue("ai_development", "AI Development"),
                SystemValue("consulting", "Consulting"),
                SystemValue("maintenance", "Maintenance"),
                SystemValue("subscription", "Subscription"),
                _other(),
            ),
            config_choices={"required_fields": REQUIRABLE_FIELDS},
        ),
        CategoryGroup(
            "expense_category",
            "Expense categories",
            "finance",
            "Classification of expenses; maps to an expense account.",
            {"default_account_id": UUID_STR, "required_fields": STR_LIST},
            (
                SystemValue("salary", "Salary"),
                SystemValue("cloud_infrastructure", "Hosting & Cloud"),
                SystemValue("software_subscriptions", "Software Subscriptions"),
                SystemValue("marketing", "Marketing"),
                SystemValue("office", "Office Expenses"),
                SystemValue("bank_fees", "Bank & Payment Fees"),
                _other(),
            ),
            config_choices={"required_fields": REQUIRABLE_FIELDS},
        ),
        CategoryGroup(
            "project_type",
            "Project types",
            "delivery",
            "Kinds of projects.",
            {"default_income_account_id": UUID_STR},
            (
                SystemValue("web_development", "Web Development"),
                SystemValue("mobile_development", "Mobile Development"),
                SystemValue("ai_development", "AI Development"),
                SystemValue("automation", "Automation"),
                SystemValue("consulting", "Consulting"),
                SystemValue("maintenance", "Maintenance"),
                _other(),
            ),
        ),
        CategoryGroup(
            "employment_type",
            "Employment types",
            "people",
            "How people are engaged.",
            {},
            (
                SystemValue("full_time", "Full-Time"),
                SystemValue("part_time", "Part-Time"),
                SystemValue("contractor", "Contractor"),
                SystemValue("freelancer", "Freelancer"),
                _other(),
            ),
        ),
        CategoryGroup(
            "compensation_type",
            "Compensation types",
            "people",
            "Labels for salary formulas.",
            {},
            (
                SystemValue("fixed_salary", "Fixed Salary"),
                SystemValue("revenue_percentage", "Revenue Percentage"),
                SystemValue("tiered_revenue_percentage", "Tiered Revenue Percentage"),
                SystemValue("fixed_plus_commission", "Fixed Salary + Commission"),
                SystemValue("bonus_based", "Bonus-Based"),
                SystemValue("custom_formula", "Custom Formula"),
                _other(),
            ),
        ),
        CategoryGroup(
            "event_type",
            "Calendar event types",
            "delivery",
            "Kinds of calendar events.",
            {"color": STR, "counts_as_unavailable": BOOL},
            (
                SystemValue("meeting", "Meeting", {"color": "blue"}),
                SystemValue("task", "Task", {"color": "slate"}, True),
                SystemValue("project_deadline", "Project Deadline", {"color": "red"}, True),
                SystemValue("milestone", "Milestone", {"color": "violet"}, True),
                SystemValue("leave", "Leave", {"color": "amber", "counts_as_unavailable": True}, True),
                SystemValue("availability", "Availability", {"color": "green"}),
                SystemValue("company_event", "Company Event", {"color": "teal"}),
                _other(),
            ),
            config_choices={"color": COLORS},
        ),
        CategoryGroup(
            "task_category",
            "Task categories",
            "delivery",
            "Kinds of tasks.",
            {"color": STR},
            (
                SystemValue("feature", "Feature"),
                SystemValue("bug", "Bug"),
                SystemValue("design", "Design"),
                SystemValue("devops", "DevOps"),
                SystemValue("research", "Research"),
                _other(),
            ),
            config_choices={"color": COLORS},
        ),
        CategoryGroup(
            "document_category",
            "Document categories",
            "general",
            "Kinds of attached documents.",
            {},
            (
                SystemValue("contract", "Contract"),
                SystemValue("receipt", "Receipt"),
                SystemValue("bank_statement", "Bank Statement"),
                SystemValue("proposal", "Proposal"),
                SystemValue("specification", "Specification"),
                _other(),
            ),
        ),
    ]
}


def system_value(group_key: str, system_key: str) -> SystemValue | None:
    group = GROUPS.get(group_key)
    return next((v for v in group.values if v.key == system_key), None) if group else None
