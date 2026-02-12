"""Application configuration."""
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings."""

    # Core API connection
    core_api_url: str = "http://localhost:8000"
    agent_api_key: str = ""  # API ключ для связи с Core API
    server_id: int = 0  # ID сервера в Core API

    # Agent settings
    agent_port: int = 8080
    agent_url: str = ""  # URL агента (будет установлен при регистрации)

    # XRay Configuration
    xray_config_path: str = "/etc/xray/config.json"
    xray_reload_command: str = "docker exec xray-server xray -test -config /etc/xray/config.json && docker exec xray-server kill -SIGHUP 1 || true"
    xray_api_address: str = "127.0.0.1:10085"  # Xray API address for Stats API

    # Metrics and monitoring
    metrics_interval: int = 30  # Отправка метрик каждые N секунд
    xray_check_interval: int = 10  # Проверка статуса XRay каждые N секунд

    # Logging
    log_level: str = "INFO"

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
    )


settings = Settings()
