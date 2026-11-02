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
    # What search-mcp searches (ADR-102): "catalog" for review text in the catalog DB, "opensearch" for review vectors.
    search_backend: str = Field(default="catalog", validation_alias="SEARCH_BACKEND")
    opensearch_url: str = Field(default="http://localhost:9200", validation_alias="OPENSEARCH_URL")
    # Any OpenAI-compatible chat completions API (ADR-91). Without a key the agent answers with the 1B rules.
    llm_base_url: str = Field(
        default="https://integrate.api.nvidia.com/v1",
        validation_alias="LLM_BASE_URL",
    )
    llm_model: str = Field(default="openai/gpt-oss-20b", validation_alias="LLM_MODEL")
    llm_api_key: str = Field(default="", validation_alias="LLM_API_KEY")
    llm_timeout_seconds: float = Field(default=60.0, validation_alias="LLM_TIMEOUT_SECONDS")


settings = Settings()
