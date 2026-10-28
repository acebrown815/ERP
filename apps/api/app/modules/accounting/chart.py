"""Default chart of accounts (docs/architecture.md, Section 6.1). Seeded once; fully editable afterwards."""

from dataclasses import dataclass


@dataclass(frozen=True)
class AccountSpec:
    code: str
    name: str
    root_type: str
    account_type: str
    parent: str | None = None
    is_group: bool = False
    currency: str | None = None  # None = base currency
    system_key: str | None = None


def _g(code: str, name: str, root: str, parent: str | None = None, key: str | None = None) -> AccountSpec:
    account_type = {"asset": "current_asset", "liability": "current_liability"}.get(root, root)
    return AccountSpec(code, name, root, account_type, parent, True, None, key)


DEFAULT_CHART: list[AccountSpec] = [
    _g("1000", "Assets", "asset"),
    _g("1100", "Bank Accounts", "asset", "1000"),
    AccountSpec("1110", "Company Checking", "asset", "bank", "1100", system_key="default_bank"),
    AccountSpec("1120", "Company Savings", "asset", "bank", "1100"),
    _g("1200", "Cash", "asset", "1000"),
    AccountSpec("1210", "Petty Cash", "asset", "cash", "1200"),
    _g("1300", "Crypto Wallets", "asset", "1000"),
    AccountSpec("1310", "Bitcoin Wallet", "asset", "crypto_wallet", "1300", currency="BTC"),
    AccountSpec("1320", "USDT Wallet", "asset", "crypto_wallet", "1300", currency="USDT"),
    _g("1900", "Other Assets", "asset", "1000"),
    AccountSpec("1990", "Other Current Assets", "asset", "current_asset", "1900"),
    _g("2000", "Liabilities", "liability"),
    _g("2300", "Credit Cards", "liability", "2000"),
    AccountSpec("2310", "Corporate Credit Card", "liability", "credit_card", "2300"),
    _g("2900", "Other Liabilities", "liability", "2000"),
    AccountSpec("2990", "Other Current Liabilities", "liability", "current_liability", "2900"),
    _g("3000", "Equity", "equity"),
    AccountSpec("3100", "Owner Capital", "equity", "equity", "3000", system_key="owner_capital"),
    AccountSpec("3200", "Owner Drawings", "equity", "equity", "3000", system_key="owner_drawings"),
    AccountSpec("3300", "Retained Earnings", "equity", "equity", "3000", system_key="retained_earnings"),
    AccountSpec("3400", "Opening Balance Equity", "equity", "equity", "3000", system_key="opening_balance_equity"),
    AccountSpec("3900", "Other Equity", "equity", "equity", "3000"),
    _g("4000", "Income", "income"),
    AccountSpec("4100", "Software Development Revenue", "income", "income", "4000", system_key="default_income"),
    AccountSpec("4200", "AI Development Revenue", "income", "income", "4000"),
    AccountSpec("4300", "Consulting Revenue", "income", "income", "4000"),
    AccountSpec("4400", "Maintenance Revenue", "income", "income", "4000"),
    AccountSpec("4500", "Subscription Revenue", "income", "income", "4000"),
    AccountSpec("4900", "Other Income", "income", "income", "4000", system_key="other_income"),
    AccountSpec("4950", "Realized FX / Crypto Gain-Loss", "income", "income", "4000", system_key="fx_gain_loss"),
    _g("5000", "Expenses", "expense"),
    AccountSpec("5100", "Employee Salaries", "expense", "expense", "5000", system_key="salary_expense"),
    AccountSpec("5200", "Cloud Infrastructure", "expense", "expense", "5000"),
    AccountSpec("5300", "Software Subscriptions", "expense", "expense", "5000"),
    AccountSpec("5400", "Marketing", "expense", "expense", "5000"),
    AccountSpec("5500", "Office Expenses", "expense", "expense", "5000"),
    AccountSpec("5600", "Bank & Payment Fees", "expense", "expense", "5000", system_key="bank_fees"),
    _g("5900", "Other Expenses", "expense", "5000"),
    AccountSpec("5990", "Miscellaneous Expenses", "expense", "expense", "5900", system_key="other_expense"),
]

# Default ledger accounts for built-in categories: (group, system_key, config key, account code).
CATEGORY_DEFAULTS: list[tuple[str, str, str, str]] = [
    ("income_category", "software_development", "default_account_id", "4100"),
    ("income_category", "ai_development", "default_account_id", "4200"),
    ("income_category", "consulting", "default_account_id", "4300"),
    ("income_category", "maintenance", "default_account_id", "4400"),
    ("income_category", "subscription", "default_account_id", "4500"),
    ("income_category", "other", "default_account_id", "4900"),
    ("expense_category", "salary", "default_account_id", "5100"),
    ("expense_category", "cloud_infrastructure", "default_account_id", "5200"),
    ("expense_category", "software_subscriptions", "default_account_id", "5300"),
    ("expense_category", "marketing", "default_account_id", "5400"),
    ("expense_category", "office", "default_account_id", "5500"),
    ("expense_category", "bank_fees", "default_account_id", "5600"),
    ("expense_category", "other", "default_account_id", "5990"),
    ("project_type", "web_development", "default_income_account_id", "4100"),
    ("project_type", "mobile_development", "default_income_account_id", "4100"),
    ("project_type", "ai_development", "default_income_account_id", "4200"),
    ("project_type", "automation", "default_income_account_id", "4100"),
    ("project_type", "consulting", "default_income_account_id", "4300"),
    ("project_type", "maintenance", "default_income_account_id", "4400"),
]
