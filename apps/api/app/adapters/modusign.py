class ModusignAdapter:
    """Template, signature request, status and webhook boundary."""

    def __init__(self, *, api_key: str, template_id: str, mode: str) -> None:
        self.api_key = api_key
        self.template_id = template_id
        self.mode = mode

    async def create_signature_request(
        self,
        *,
        contract_id: str,
        template_data: dict[str, str],
    ) -> str:
        raise NotImplementedError("Day 5 모두싸인 연동에서 구현합니다.")
