
from pydantic import BaseModel, ConfigDict, Field


class DatasourceConfig(BaseModel):
    """
    单个数据源的配置模型

    用于表示 datasource.yml 中的单个数据源配置项
    """
    name: str
    url: str
    db_schema: str = Field(default="public", alias="schema")
    pool_size: int = 10
    max_overflow: int = 20
    pool_timeout: int = 30
    echo: bool = False
    description: str | None = None

    model_config = ConfigDict(populate_by_name=True)
