from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    host: str = Field(default="127.0.0.1", validation_alias="AGENT_SERVICE_HOST")
    port: int = Field(default=8000, validation_alias="AGENT_SERVICE_PORT")
    catalog_service_url: str = Field(
        default="http://localhost:8081",
        validation_alias="CATALOG_SERVICE_URL",
    )
    order_service_url: str = Field(
        default="http://localhost:8082",
        validation_alias="ORDER_SERVICE_URL",
    )


settings = Settings()
