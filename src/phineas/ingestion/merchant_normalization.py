def normalize_merchant_name(merchant_name: str) -> str:
    """Normalize an already extracted merchant name for exact grouping."""
    normalized = " ".join(merchant_name.casefold().split())
    if not normalized:
        raise ValueError("merchant_name must be nonblank")

    return normalized
