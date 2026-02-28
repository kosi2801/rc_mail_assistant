from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # Required
    secret_key: str
    postgres_user: str = "rcmail"
    postgres_password: str
    postgres_db: str = "rcmail"
    postgres_host: str = "postgres"
    postgres_port: int = 5432

    # Optional
    ollama_base_url: str = ""
    gmail_client_id: str = ""
    gmail_client_secret: str = ""
    gmail_refresh_token: str = ""

    # Startup retry tuning
    db_connect_attempts: int = 5
    db_connect_delay_seconds: int = 2

    @property
    def database_url(self) -> str:
        return (
            f"postgresql+asyncpg://{self.postgres_user}:{self.postgres_password}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )


settings = Settings()
