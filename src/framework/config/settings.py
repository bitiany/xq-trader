import os

from dotenv import load_dotenv
from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from framework.commons.crypto.crypto import CryptoUtils

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
_DEFAULT_ENV_FILE = os.path.join(_PROJECT_ROOT, ".env")


def _normalize_env_path(path: str) -> str:
    return os.path.normcase(os.path.abspath(path))


def _resolve_env_file(path: str) -> str:
    if os.path.isabs(path):
        return path
    return os.path.join(_PROJECT_ROOT, path)


def _load_env() -> None:
    load_dotenv(_DEFAULT_ENV_FILE)
    override_path = os.getenv("APP_ENV_FILE") or os.getenv("ENV")
    if override_path:
        resolved = _resolve_env_file(override_path)
        if _normalize_env_path(resolved) != _normalize_env_path(_DEFAULT_ENV_FILE):
            load_dotenv(resolved, override=True)
    pg_new_password = os.getenv("PG_NEW_PASSWORD")
    if pg_new_password:
        if not os.getenv("DATABASES_DEFAULT_PASSWORD"):
            os.environ["DATABASES_DEFAULT_PASSWORD"] = pg_new_password
        if not os.getenv("DATABASES_STOCK_PASSWORD"):
            os.environ["DATABASES_STOCK_PASSWORD"] = pg_new_password
        if not os.getenv("DATABASES_RESEARCH_PASSWORD"):
            os.environ["DATABASES_RESEARCH_PASSWORD"] = pg_new_password


_load_env()

if "PYTHONUTF8" not in os.environ:
    os.environ["PYTHONUTF8"] = "1"

class AppSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="APP_")

    TITLE: str = "Server"
    VERSION: str = "0.1.0"
    DESCRIPTION: str = "Server API"
    DEBUG: bool = False
    API_PREFIX: str = "/api/v1"
    PORT: int = 8096
    API_KEY: str | None = None
    ROOT_DIR: str = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
    STORAGE_DIR: str = ""
    DB_CONFIG_PATH: str = "datasource.yml"
    FACTOR_LAB_AUTO_SEED: bool = True
    GENERATE_SCHEMA_ON_START: bool = True
    #: 是否在启动时自动生成数据库表结构（仅在开发环境下有效）

    @model_validator(mode="after")
    def post_process(self) -> "AppSettings":
        object.__setattr__(
            self,
            "API_KEY",
            CryptoUtils.decrypt_if_encrypted(self.API_KEY),
        )

        db_config_path = self.DB_CONFIG_PATH
        if not os.path.isabs(db_config_path):
            object.__setattr__(
                self,
                "DB_CONFIG_PATH",
                os.path.join(self.ROOT_DIR, db_config_path),
            )

        storage_dir = self.STORAGE_DIR
        if not storage_dir:
            object.__setattr__(
                self,
                "STORAGE_DIR",
                os.path.join(self.ROOT_DIR, "storage"),
            )
        elif not os.path.isabs(storage_dir):
            object.__setattr__(
                self,
                "STORAGE_DIR",
                os.path.join(self.ROOT_DIR, storage_dir),
            )

        return self


class QmtSettings(BaseSettings):
    model_config = SettingsConfigDict(extra="ignore")

    QMT_PATH: str = ""
    QMT_USERDATA_PATH: str = ""
    QMT_ACCOUNT_ID: str = ""
    QMT_ACCOUNT_TYPE: str = "STOCK"
    QMT_POLL_INTERVAL_MS: int = 3000
    QMT_CONNECT_TIMEOUT: int = 10


class GraphSettings(BaseSettings):
    model_config = SettingsConfigDict(extra="ignore")

    GRAPH_MAX_NODES: int = 500
    GRAPH_MAX_EDGES: int = 2000
    GRAPH_DEFAULT_PRODUCT_LIMIT: int = 10
    GRAPH_DEFAULT_COMPANY_LIMIT: int = 80
    GRAPH_MAX_PATH_HOPS: int = 6


class Neo4jSettings(BaseSettings):
    model_config = SettingsConfigDict(extra="ignore")

    NEO4J_HOST: str = "localhost"
    NEO4J_PORT: int = 7687
    NEO4J_USER: str = "neo4j"
    NEO4J_PASSWORD: str = ""
    NEO4J_DATABASE: str = "neo4j"
    NEO4J_MAX_POOL_SIZE: int = 50
    NEO4J_QUERY_TIMEOUT: int = 10


class RedisSettings(BaseSettings):
    model_config = SettingsConfigDict(extra="ignore")

    REDIS_HOST: str = "127.0.0.1"
    REDIS_PORT: int = 6379
    REDIS_PASSWORD: str = ""
    REDIS_DB: int = 0

    @property
    def url(self) -> str:
        if self.REDIS_PASSWORD:
            return (
                f"redis://:{self.REDIS_PASSWORD}@{self.REDIS_HOST}:"
                f"{self.REDIS_PORT}/{self.REDIS_DB}"
            )
        return f"redis://{self.REDIS_HOST}:{self.REDIS_PORT}/{self.REDIS_DB}"


class AgentApiSettings(BaseSettings):
    model_config = SettingsConfigDict(extra="ignore")

    AGENT_SSE_BLOCK_MS: int = 5000
    AGENT_SSE_IDLE_TIMEOUT_S: float = 600.0
    AGENT_DEFAULT_MODEL: str = ""


class CollectSettings(BaseSettings):
    model_config = SettingsConfigDict(extra="ignore")

    COLLECT_REDIS_URL: str = ""
    COLLECT_REDIS_DB: int = 3


class JupyterSettings(BaseSettings):
    model_config = SettingsConfigDict(extra="ignore")

    JUPYTER_PORT: int = 8888
    JUPYTER_TOKEN: str = ""
    JUPYTER_NOTEBOOK_DIR: str = ""


class CelerySettings(BaseSettings):
    model_config = SettingsConfigDict(extra="ignore")

    CELERY_REDIS_DB: int = 1
    CELERY_BROKER_URL: str = ""
    CELERY_RESULT_BACKEND: str = ""


class Settings:
    """应用配置容器（APP 子配置独立读取 APP_* 环境变量）。"""

    def __init__(self) -> None:
        self.APP = AppSettings()
        qmt = QmtSettings()
        object.__setattr__(
            qmt,
            "QMT_ACCOUNT_ID",
            CryptoUtils.decrypt_if_encrypted(qmt.QMT_ACCOUNT_ID) or "",
        )
        if not qmt.QMT_USERDATA_PATH and qmt.QMT_PATH:
            object.__setattr__(qmt, "QMT_USERDATA_PATH", qmt.QMT_PATH)
        self.QMT = qmt
        self.GRAPH = GraphSettings()
        self.NEO4J = Neo4jSettings()
        redis = RedisSettings()
        object.__setattr__(
            redis,
            "REDIS_PASSWORD",
            CryptoUtils.decrypt_if_encrypted(redis.REDIS_PASSWORD),
        )
        self.REDIS = redis
        self.AGENT = AgentApiSettings()
        self.COLLECT = CollectSettings()
        self.JUPYTER = JupyterSettings()
        self.CELERY = CelerySettings()


settings = Settings()
