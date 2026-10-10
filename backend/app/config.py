from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(ROOT / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    desk_database: str = "data/desk.db"
    desk_refresh_hour: int = 8
    desk_timezone: str = "Asia/Shanghai"
    reddit_client_id: str = ""
    reddit_client_secret: str = ""
    reddit_username: str = ""
    seed_path: str = ""

    @property
    def database_path(self) -> Path:
        path = Path(self.desk_database)
        if not path.is_absolute():
            path = ROOT / path
        return path


settings = Settings()
