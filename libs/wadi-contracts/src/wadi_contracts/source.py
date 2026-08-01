"""Source anchoring: every extracted fact points back at real code (§7)."""

from typing import Self

from pydantic import Field, model_validator

from wadi_contracts.base import WadiModel
from wadi_contracts.enums import SourceVariant


class SourceAnchor(WadiModel):
    """A file + line range in the text that was actually analyzed.

    For preprocessed files (delombok) the anchor refers to the generated
    variant — source-on-demand serves that same text, so anchors and served
    source stay aligned by construction (§5.3).
    """

    file: str = Field(min_length=1, description="Path relative to the service build root")
    start_line: int = Field(ge=1)
    end_line: int = Field(ge=1)
    variant: SourceVariant = SourceVariant.ORIGINAL

    @model_validator(mode="after")
    def _check_range(self) -> Self:
        if self.end_line < self.start_line:
            raise ValueError(
                f"end_line ({self.end_line}) must be >= start_line ({self.start_line})"
            )
        return self


class MethodRef(WadiModel):
    """Reference to a method: stable content-derived id + human-readable signature."""

    id: str = Field(min_length=1, pattern=r"^m_[0-9a-f]{16}$")
    signature: str = Field(min_length=1, description="Fully-qualified method signature")
