from ..config import Settings
from .base import Provider
from .llm import BedrockProvider, VertexProvider
from .rules import RuleProvider

PROVIDERS = ("rules", "bedrock", "vertex")


def get_provider(name: str, cfg: Settings) -> Provider:
    if name == "rules":
        return RuleProvider()
    if name == "bedrock":
        return BedrockProvider(cfg.bedrock_model, cfg.aws_region)
    if name == "vertex":
        return VertexProvider(cfg.gemini_model, cfg.gcp_project, cfg.gcp_location)
    raise ValueError(f"unknown provider: {name}. Available: {', '.join(PROVIDERS)}")


def all_providers(cfg: Settings) -> list[Provider]:
    return [get_provider(n, cfg) for n in PROVIDERS]


__all__ = [
    "PROVIDERS",
    "BedrockProvider",
    "Provider",
    "RuleProvider",
    "VertexProvider",
    "all_providers",
    "get_provider",
]
