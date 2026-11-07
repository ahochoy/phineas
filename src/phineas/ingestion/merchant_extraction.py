def extract_canonical_merchant(description: str) -> str | None:
    description = description.strip()
    prefix = "MERCHANT:"

    if not description.startswith(prefix):
        return None

    merchant_name = description.removeprefix(prefix).partition("|")[0].strip()

    return merchant_name or None
