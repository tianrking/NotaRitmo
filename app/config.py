from functools import lru_cache
from uuid import UUID

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore", case_sensitive=False)

    app_name: str = "NotaRitmo"
    app_version: str = "0.1.0"
    database_url: str = "postgresql+psycopg://meeting:meeting@postgres:5432/meeting"

    minio_endpoint: str = "minio:9000"
    minio_access_key: str = "meeting-minio"
    minio_secret_key: str = "meeting-minio-secret"
    minio_bucket: str = "meeting-audio"
    minio_secure: bool = False
    minio_public_endpoint: str = "localhost:9000"
    minio_public_secure: bool = False
    minio_region: str = "us-east-1"
    upload_url_ttl_seconds: int = 3600
    audio_max_bytes: int = 6 * 1024 * 1024 * 1024
    audio_max_duration_seconds: int = 6 * 60 * 60
    audio_preprocess_version: str = "ffmpeg-v1"
    audio_denoise_default: bool = False
    ffmpeg_binary: str = "ffmpeg"
    ffprobe_binary: str = "ffprobe"
    speaker_embedding_enabled: bool = True
    speaker_embedding_model: str = (
        "/models/speaker/3dspeaker_speech_campplus_sv_zh-cn_16k-common.onnx"
    )
    speaker_embedding_model_version: str = "3dspeaker-campplus-16k-v1"
    speaker_embedding_dimensions: int = 192
    speaker_embedding_threads: int = 2
    speaker_match_threshold: float = 0.62
    speaker_min_enrollment_ms: int = 3000
    speaker_max_sample_ms: int = 60000

    temporal_address: str = "temporal:7233"
    temporal_namespace: str = "default"
    temporal_task_queue: str = "meeting-ingest"

    default_tenant_id: UUID = UUID("00000000-0000-0000-0000-000000000001")
    default_user_id: UUID = UUID("00000000-0000-0000-0000-000000000001")
    public_api_base_url: str = "http://localhost:4200"
    provider_audio_secret: str = "change-provider-audio-secret"
    provider_audio_url_ttl_seconds: int = 86400
    hera_auth_required: bool = False
    hera_signing_secret: str = "change-hera-signing-secret"
    hera_signature_max_skew_seconds: int = 300
    hera_outbox_schema_version: str = "hera-meeting-intelligence-v1"

    tingwu_enabled: bool = False
    tingwu_app_key: str = ""
    tingwu_region: str = "cn-beijing"
    tingwu_domain: str = "tingwu.cn-beijing.aliyuncs.com"
    tingwu_source_language: str = "cn"
    tingwu_poll_seconds: int = 60
    tingwu_llm_model: str = "qwen-plus"
    alibaba_cloud_access_key_id: str = ""
    alibaba_cloud_access_key_secret: str = ""

    llm_enabled: bool = False
    llm_base_url: str = "http://host.docker.internal:4000/v1"
    llm_api_key: str = ""
    llm_model: str = ""
    llm_provider: str = "openai-compatible"
    llm_prompt_version: str = "meeting-unified-v1"
    llm_schema_version: str = "meeting-components-v1"
    llm_input_cost_per_million: float = 0.0
    llm_output_cost_per_million: float = 0.0
    llm_max_transcript_characters: int = 240_000
    embedding_model: str = ""
    embedding_dimensions: int = Field(default=384, ge=1, le=4096)
    local_embeddings_enabled: bool = True
    local_embedding_model: str = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
    local_embedding_cache: str = "/models/fastembed"

    graph_memory_enabled: bool = True
    graphiti_enabled: bool = False
    neo4j_uri: str = "bolt://neo4j:7687"
    neo4j_user: str = "neo4j"
    neo4j_password: str = "change-neo4j-password"


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
