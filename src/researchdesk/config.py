from pathlib import Path
from typing import Literal

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="RESEARCHDESK_", env_file=".env", extra="ignore")

    database_url: str = "sqlite:///./data/researchdesk.db"
    provider: Literal["disabled", "openai", "claude_cli"] = "disabled"
    model: str = ""
    openai_api_key: SecretStr = SecretStr("")
    alpaca_api_key: SecretStr = SecretStr("")
    alpaca_secret_key: SecretStr = SecretStr("")
    alpaca_feed: Literal["iex", "sip"] = "iex"
    operator_token: SecretStr = SecretStr("")
    read_only: bool = False
    claude_binary: str = "claude"
    provider_timeout_seconds: int = Field(default=120, ge=5, le=600)
    max_turns: int = Field(default=20, ge=1, le=100)
    allowed_origins: str = (
        "http://127.0.0.1:3000,http://localhost:3000,http://127.0.0.1:8010,http://localhost:8010"
    )
    docker_binary: str = "docker"
    sandbox_image: str = "researchdesk-sandbox:local"
    sandbox_timeout_seconds: int = Field(default=20, ge=1, le=120)
    artifact_dir: Path = Path("artifacts")
    embedding_model: str = "BAAI/bge-small-en-v1.5"
    retrieval_mode: Literal["lexical", "dense"] = "lexical"
    max_evidence_bytes: int = Field(default=1_000_000, ge=1000, le=5_000_000)
    allowed_evidence_hosts: str = (
        "clinicaltrials.gov,pubmed.ncbi.nlm.nih.gov,pmc.ncbi.nlm.nih.gov,"
        "www.sec.gov,sec.gov,www.fda.gov,fda.gov,arxiv.org,"
        "www.federalreserve.gov,fred.stlouisfed.org"
    )
