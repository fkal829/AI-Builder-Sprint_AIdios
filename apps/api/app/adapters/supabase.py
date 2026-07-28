class SupabaseAdapter:
    """PostgreSQL and private contract storage boundary."""

    def __init__(self, *, url: str, service_role_key: str, bucket: str) -> None:
        self.url = url
        self.service_role_key = service_role_key
        self.bucket = bucket
