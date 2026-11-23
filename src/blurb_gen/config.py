from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="BG_",
        env_file=".env",
        extra="ignore",
    )

    templates_path: Path = Path("data/templates.yaml")
    guidelines_path: Path = Path("data/guidelines.yaml")

    provider: str = "rules"
    template_version: int = 0
    quality_threshold: float = 75.0
    confidence_threshold: float = 60.0

    aws_region: str = "us-east-1"
    bedrock_model: str = "us.anthropic.claude-haiku-4-5-20251001-v1:0"

    gcp_project: str = ""
    gcp_location: str = "us-central1"
    gemini_model: str = "gemini-1.5-flash"

    output_format: str = "csv"
    log_level: str = "INFO"


settings = Settings()
