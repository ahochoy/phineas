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
