from uuid import uuid4


class MerchantRegistry:
    def __init__(self) -> None:
        self._merchant_ids: dict[str, str] = {}

    def get_or_create(self, normalized_merchant: str) -> str:
        if not normalized_merchant.strip():
            raise ValueError("normalized_merchant must be nonblank")

        existing_id = self._merchant_ids.get(normalized_merchant)

        if existing_id is not None:
            return existing_id

        merchant_id = f"merchant_{uuid4().hex}"
        self._merchant_ids[normalized_merchant] = merchant_id
        return merchant_id
