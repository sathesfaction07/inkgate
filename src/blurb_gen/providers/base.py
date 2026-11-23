from abc import ABC, abstractmethod

from ..core.guidelines import Guidelines
from ..models import Case, Classification, QualityReport
from ..templates.registry import Template


class Provider(ABC):
    name: str

    @abstractmethod
    def is_available(self) -> bool: ...

    @abstractmethod
    def classify(self, case: Case, templates: list[Template]) -> Classification | None: ...

    @abstractmethod
    def score(
        self, text: str, template: Template, guidelines: Guidelines
    ) -> QualityReport | None: ...
