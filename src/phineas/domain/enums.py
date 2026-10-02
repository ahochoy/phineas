from enum import StrEnum


class Direction(StrEnum):
    INFLOW = "inflow"
    OUTFLOW = "outflow"


class AccountType(StrEnum):
    CHECKING = "checking"
    CREDIT_CARD = "credit_card"


class Currency(StrEnum):
    USD = "USD"


class TransactionKind(StrEnum):
    PURCHASE = "purchase"
    PAYMENT = "payment"
    REFUND = "refund"
    TRANSFER = "transfer"
    INCOME = "income"
    FEE = "fee"
    INTEREST = "interest"
    CASH_WITHDRAWAL = "cash_withdrawal"
    UNKNOWN = "unknown"


class ClassificationSource(StrEnum):
    SOURCE = "source"
    RULE = "rule"
    LAYA = "laya"
    UNKNOWN = "unknown"


class DocumentOrigin(StrEnum):
    BUNDLED_SAMPLE = "bundled_sample"
    PRIVATE_UPLOAD = "private_upload"


class SpendingCategory(StrEnum):
    GROCERIES = "groceries"
    DINING = "dining"
    TRANSPORTATION = "transportation"
    HOUSING = "housing"
    UTILITIES = "utilities"
    HEALTHCARE = "healthcare"
    SHOPPING = "shopping"
    ENTERTAINMENT = "entertainment"
    TRAVEL = "travel"
    EDUCATION = "education"
    PERSONAL_CARE = "personal_care"
    FINANCIAL_SERVICES = "financial_services"
    OTHER = "other"
    UNKNOWN = "unknown"


class AnalysisFlag(StrEnum):
    RECURRING_CANDIDATE = "recurring_candidate"
    PRICE_CHANGE_CANDIDATE = "price_change_candidate"
    FEE_CANDIDATE = "fee_candidate"
    DUPLICATE_CANDIDATE = "duplicate_candidate"
