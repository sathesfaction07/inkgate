from pathlib import Path

import yaml
from pydantic import BaseModel, Field

from ..models import Decision


class RequiredElement(BaseModel):
    id: str
    any_of: list[str] = Field(default_factory=list)
    weight: float = 1.0
    detail: str = ""
    applies_to_decisions: list[Decision] = Field(default_factory=list)

    def applies(self, decision: Decision) -> bool:
        return not self.applies_to_decisions or decision in self.applies_to_decisions


class Guidelines(BaseModel):
    version: int = 1
    banned_phrases: list[str] = Field(default_factory=list)
    required_elements: list[RequiredElement] = Field(default_factory=list)
    tone_notes: list[str] = Field(default_factory=list)

    @classmethod
    def load(cls, path: Path) -> "Guidelines":
        if not path.exists():
            raise FileNotFoundError(f"guidelines not found: {path}")
        raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        return cls(**raw)

    def elements_for(self, decision: Decision) -> list[RequiredElement]:
        return [e for e in self.required_elements if e.applies(decision)]

    def as_prompt_block(self, decision: Decision | None = None) -> str:
        lines = [f"GUIDELINES (version {self.version})"]

        if self.banned_phrases:
            lines.append("Never use these phrases:")
            lines.extend(f"  - {p}" for p in self.banned_phrases)

        scoped = self.elements_for(decision) if decision else self.required_elements
        if scoped:
            lines.append("The blurb must contain each of these:")
            for element in scoped:
                detail = f" ({element.detail})" if element.detail else ""
                lines.append(f"  - {element.id}{detail}")

        if self.tone_notes:
            lines.append("Tone:")
            lines.extend(f"  - {n}" for n in self.tone_notes)

        return "\n".join(lines)
