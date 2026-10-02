"""Contrato serializable del editor por fragmentos (unidades PDF, sin Qt)."""
from dataclasses import dataclass, field


@dataclass
class RichTextRequest:
    page: int
    ids: list[int]
    runs: list[dict]
    rect: tuple | list | None = None
    width: float | None = None
    height: float | None = None
    paragraphs: list[dict] = field(default_factory=list)
    revision: str | None = None
    allow_overlap: bool = False
    auto_width: bool = False
    auto_height: bool = False

