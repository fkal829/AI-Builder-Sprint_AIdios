import re
from collections.abc import Iterable

UNSAFE_CONCLUSION_PATTERNS = (
    r"(?:사기(?:의심)?(?:업체|대행사|계약)|"
    r"(?:이)?(?:업체|대행사|계약)(?:는|가|은|이).{0,8}사기"
    r"(?:입니다|이다|라고|의심|확실))",
    r"(?:불법(?:인)?(?:계약|조항)|"
    r"(?:이)?(?:계약|조항)(?:은|이|가).{0,8}(?:불법|위법)"
    r"(?:입니다|이다|이라고|확정))",
    r"(?:안전한(?:업체|대행사)|"
    r"(?:이)?(?:업체|대행사)(?:는|가|은|이).{0,8}안전"
    r"(?:합니다|하다|하다고|한곳(?:입니다|이다)?|함|보장))",
    r"(?:승소(?:할)?수있|승소(?:할)?가능성(?:이)?(?:높|있|크|확실)|"
    r"승소확률|승소.{0,6}(?:확실|확정|보장)|(?:반드시|확실히)승소)",
    r"(?:법률자문|법률상담).{0,12}(?:대체(?:합니다|한다|할수있|가능)|"
    r"대신(?:합니다|한다)|받지않아도|필요없|불필요)",
)


def contains_unsafe_legal_conclusion(values: Iterable[str]) -> bool:
    normalized = re.sub(r"[\W_]+", "", " ".join(values)).lower()
    return any(re.search(pattern, normalized) for pattern in UNSAFE_CONCLUSION_PATTERNS)
