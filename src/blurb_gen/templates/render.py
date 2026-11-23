from .registry import PLACEHOLDER, Template


class MissingVariablesError(Exception):
    def __init__(self, missing: set[str]) -> None:
        self.missing = missing
        super().__init__(f"missing required variables: {sorted(missing)}")


def render(template: Template, variables: dict[str, str]) -> str:
    supplied = {k: v for k, v in variables.items() if v}
    missing = set(template.required_variables) - set(supplied)
    if missing:
        raise MissingVariablesError(missing)

    body = template.body
    for key, value in supplied.items():
        body = body.replace(f"{{{key}}}", value)

    return _tidy(body)


def leftover_placeholders(text: str) -> set[str]:
    return set(PLACEHOLDER.findall(text))


def _tidy(text: str) -> str:
    lines = [line.rstrip() for line in text.strip().splitlines()]
    tidied: list[str] = []
    for line in lines:
        if not line and tidied and not tidied[-1]:
            continue
        tidied.append(line)
    return "\n".join(tidied)
