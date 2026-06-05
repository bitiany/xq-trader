import logging
from pathlib import Path
from typing import Any
from urllib.parse import quote_plus

import yaml

from framework.commons.resolver import PlaceholderResolver
from framework.dal.datasource import DatasourceConfig

logger = logging.getLogger("DATASOURCE_LOADER")


class DatasourceLoader:

    def __init__(self, config_path: str):
        self.config_path = config_path
        self.datasources: dict[str, DatasourceConfig] = {}
        self.timescale_config: dict = {}
        self.load()

    def load(self) -> None:
        """加载数据源配置。"""
        p = Path(self.config_path)
        logger.debug(f"Loading datasource config from {p}")
        if not p.exists():
            raise FileNotFoundError(f"Datasource config file not found: {p}")
        with open(p, encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}

        self.raw_config = PlaceholderResolver().resolve_dict(data)

        datasource_configs = self.raw_config.get("datasource", {})
        for name, datasource_config in datasource_configs.items():
            if isinstance(datasource_config, dict):
                self.datasources[name] = self.build_datasources(name, datasource_config)

        self.timescale_config = self.raw_config.get("timescale", {})

    def build_datasources(self,name:str, datasource_config: dict[str, Any])  -> DatasourceConfig:
        """
        构建数据源配置
        """
        if "url" in datasource_config:
            url = str(datasource_config.get("url", ""))
        else:
            password = datasource_config.get("password")
            # 对密码进行 URL 编码，处理特殊字符如 @
            encoded_password = quote_plus(password) if password else None
            url = (
                f"{datasource_config.get('driver')}://{datasource_config.get('user')}"
                f":{encoded_password}@{datasource_config.get('host')}"
                f":{datasource_config.get('port')}/{datasource_config.get('db_name')}"
            )
        
        pool_size = datasource_config.get("pool_size", 15)
        if isinstance(pool_size, str):
            pool_size = int(pool_size)
        
        max_overflow = datasource_config.get("max_overflow", 20)
        if isinstance(max_overflow, str):
            max_overflow = int(max_overflow)
        
        pool_timeout = datasource_config.get("pool_timeout", 30)
        if isinstance(pool_timeout, str):
            pool_timeout = int(pool_timeout)
        
        echo = datasource_config.get("echo", False)
        if isinstance(echo, str):
            echo = echo.lower() in ('true', '1', 'yes', 'on')
        
        return DatasourceConfig(
            name=name,
            url=url,
            schema=datasource_config.get("schema", "public"),
            pool_size=pool_size,
            max_overflow=max_overflow,
            pool_timeout=pool_timeout,
            echo=echo,
        )
