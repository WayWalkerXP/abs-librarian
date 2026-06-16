from __future__ import annotations
from functools import lru_cache
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file='.env', env_prefix='ABS_LIBRARIAN_', extra='ignore')
    database_url: str = 'postgresql+psycopg://abs_librarian:abs_librarian@postgres:5432/abs_librarian'
    secret_key: str = 'change-me-in-production'
    incoming_dir: str = '/data/incoming'
    staging_dir: str = '/data/staging'
    converting_dir: str = '/data/converting'
    ready_for_library_dir: str = '/data/ready_for_library'
    library_dir: str = '/data/library'
    converted_dir: str = '/data/converted'
    failed_dir: str = '/data/failed'
    logs_dir: str = '/data/logs'
    temp_dir: str = '/data/temp'
    metadata_backup_dir: str = '/data/metadata_backups'
    output_template: str = '{author}/{series}/{series_sequence} - {album}'
    abs_base_url: str = ''
    abs_api_token: str = ''
    abs_library_id: str = ''
    abs_cache_refresh_hours: int = 24
    default_bitrate_kbps: int = Field(default=64, ge=25, le=384)
    default_channels: int = Field(default=1, ge=1, le=2)
    max_concurrent_jobs: int = 1
    log_retention_days: int = 30

@lru_cache
def get_settings() -> Settings:
    return Settings()
