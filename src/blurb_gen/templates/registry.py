import re
from pathlib import Path

import yaml
from pydantic import BaseModel, Field, field_validator

from ..models import Decision

PLACEHOLDER = re.compile(r"\{([a-z0-9_]+)\}")


class LengthBounds(BaseModel):
    min_chars: int = 0
    max_chars: int = 10_000

    @field_validator("max_chars")
    @classmethod
    def sane_bounds(cls, v: int, info) -> int:
        minimum = info.data.get("min_chars", 0)
        if v <= minimum:
            raise ValueError(f"max_chars ({v}) must exceed min_chars ({minimum})")
        return v


class AppliesTo(BaseModel):
    decision: Decision
    reasons: list[str] = Field(default_factory=list)
    categories: list[str] = Field(default_factory=list)


class Template(BaseModel):
    id: str
    version: int
    applies_to: AppliesTo
    required_variables: list[str] = Field(default_factory=list)
    length: LengthBounds = Field(default_factory=LengthBounds)
    body: str

    @property
    def placeholders(self) -> set[str]:
        return set(PLACEHOLDER.findall(self.body))

    def undeclared_placeholders(self) -> set[str]:
        return self.placeholders - set(self.required_variables)

    def unused_declarations(self) -> set[str]:
        return set(self.required_variables) - self.placeholders

    def matches(self, decision: Decision, reason: str, category: str) -> int:
        if self.applies_to.decision is not decision:
            return 0

        score = 1
        reason_lower = reason.lower()
        if self.applies_to.reasons:
            if not any(r.lower() in reason_lower for r in self.applies_to.reasons):
                return 0
            score += 2

        if self.applies_to.categories:
            if category.lower() not in [c.lower() for c in self.applies_to.categories]:
                return 0
            score += 1

        return score


class TemplateSet(BaseModel):
    version: int
    templates: list[Template]

    def by_id(self, template_id: str) -> Template | None:
        return next((t for t in self.templates if t.id == template_id), None)


class TemplateRegistry:
    def __init__(self, template_set: TemplateSet) -> None:
        self.set = template_set

    @classmethod
    def load(cls, path: Path) -> "TemplateRegistry":
        if not path.exists():
            raise FileNotFoundError(f"templates not found: {path}")
        raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        return cls(TemplateSet(**raw))

    @property
    def version(self) -> int:
        return self.set.version

    def all(self) -> list[Template]:
        return list(self.set.templates)

    def get(self, template_id: str) -> Template | None:
        return self.set.by_id(template_id)

    def select(self, decision: Decision, reason: str = "", category: str = "") -> Template | None:
        scored = [(t.matches(decision, reason, category), t) for t in self.set.templates]
        eligible = [(s, t) for s, t in scored if s > 0]
        if not eligible:
            return None
        best = max(s for s, _ in eligible)
        return sorted((t for s, t in eligible if s == best), key=lambda t: t.id)[0]

    def validate(self) -> list[str]:
        problems: list[str] = []
        seen: dict[str, int] = {}

        for template in self.set.templates:
            if template.id in seen:
                problems.append(f"{template.id}: duplicate template id")
            seen[template.id] = template.version

            undeclared = template.undeclared_placeholders()
            if undeclared:
                problems.append(
                    f"{template.id}: body uses undeclared variables "
                    f"{sorted(undeclared)} - add them to required_variables"
                )

            unused = template.unused_declarations()
            if unused:
                problems.append(
                    f"{template.id}: declares {sorted(unused)} but the body never uses them"
                )

            if not template.body.strip():
                problems.append(f"{template.id}: body is empty")

            if template.version > self.set.version:
                problems.append(
                    f"{template.id}: version {template.version} exceeds set version "
                    f"{self.set.version}"
                )

            floor = len(template.body)
            if template.length.max_chars < floor:
                problems.append(
                    f"{template.id}: max_chars {template.length.max_chars} is below the "
                    f"unrendered body length {floor}, so it can never pass"
                )

        return problems
