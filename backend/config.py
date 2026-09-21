from pathlib import Path
from typing import Literal
from urllib.parse import urlsplit

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_ROOT = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=PROJECT_ROOT / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=True,
    )

    app_env: Literal["development", "test", "production"] = Field(
        default="development",
        validation_alias="APP_ENV",
    )
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = Field(
        default="INFO",
        validation_alias="LOG_LEVEL",
    )
    database_path: Path = Field(
        default=PROJECT_ROOT / "dnd_planner.db",
        validation_alias="DATABASE_PATH",
    )
    database_url: SecretStr | None = Field(
        default=None,
        validation_alias="DATABASE_URL",
    )
    mutations_enabled: bool = Field(
        default=True,
        validation_alias="MUTATIONS_ENABLED",
    )
    cors_allowed_origins: list[str] = Field(
        default_factory=lambda: [
            "http://localhost:3000",
            "http://127.0.0.1:3000",
        ],
        validation_alias="CORS_ALLOWED_ORIGINS",
    )
    clerk_secret_key: SecretStr | None = Field(
        default=None,
        validation_alias="CLERK_SECRET_KEY",
    )
    clerk_authorized_parties: list[str] = Field(
        default_factory=list,
        validation_alias="CLERK_AUTHORIZED_PARTIES",
    )

    @field_validator("database_path")
    @classmethod
    def resolve_database_path(cls, value: Path) -> Path:
        path = value.expanduser()
        if not path.is_absolute():
            path = PROJECT_ROOT / path
        path = path.resolve()
        if not path.parent.is_dir():
            raise ValueError("DATABASE_PATH parent directory does not exist")
        return path

    @field_validator("database_url", mode="before")
    @classmethod
    def normalize_optional_database_url(cls, value: object) -> object:
        if isinstance(value, str) and not value.strip():
            return None
        return value

    @field_validator("cors_allowed_origins")
    @classmethod
    def validate_cors_allowed_origins(cls, value: list[str]) -> list[str]:
        origins = [origin.strip().rstrip("/") for origin in value if origin.strip()]
        if not origins:
            raise ValueError("CORS_ALLOWED_ORIGINS must contain at least one origin")
        for origin in origins:
            parsed = urlsplit(origin)
            if (
                parsed.scheme not in {"http", "https"}
                or not parsed.netloc
                or parsed.path
                or parsed.query
                or parsed.fragment
            ):
                raise ValueError(
                    "CORS_ALLOWED_ORIGINS entries must be HTTP(S) origins without paths"
                )
        return origins

    @field_validator("clerk_authorized_parties")
    @classmethod
    def validate_clerk_authorized_parties(cls, value: list[str]) -> list[str]:
        origins = [origin.strip().rstrip("/") for origin in value if origin.strip()]
        for origin in origins:
            parsed = urlsplit(origin)
            if (
                parsed.scheme not in {"http", "https"}
                or not parsed.netloc
                or parsed.path
                or parsed.query
                or parsed.fragment
            ):
                raise ValueError(
                    "CLERK_AUTHORIZED_PARTIES entries must be HTTP(S) origins "
                    "without paths"
                )
        return origins

    def validate_production_clerk_configuration(self) -> None:
        """Reject an incomplete production web-runtime authentication policy."""
        if self.app_env != "production":
            return
        if (
            self.clerk_secret_key is None
            or not self.clerk_secret_key.get_secret_value().strip()
        ):
            raise ValueError("CLERK_SECRET_KEY is required in production")
        if not self.clerk_authorized_parties:
            raise ValueError("CLERK_AUTHORIZED_PARTIES is required in production")


settings = Settings()
