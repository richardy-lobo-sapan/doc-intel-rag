from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # Postgres / pgvector
    database_url: str = "postgresql://raguser:ragpass@localhost:5432/ragdb"

    # Embedding model (local, via sentence-transformers)
    embedding_model_name: str = "intfloat/multilingual-e5-base"
    embedding_dim: int = 768

    # LLM (Groq)
    groq_api_key: str = ""
    groq_model: str = "llama-3.3-70b-versatile"

    # Retrieval
    top_k: int = 5

    # Optional observability
    langfuse_public_key: str = ""
    langfuse_secret_key: str = ""
    langfuse_host: str = "https://cloud.langfuse.com"


settings = Settings()
