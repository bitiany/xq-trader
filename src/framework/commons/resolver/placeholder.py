"""
通用占位符解析器

基于 JSONPath 实现，支持配置中心和工作流两种场景。

特性：
- 统一语法：${variable} 或 ${variable:-default}
- 自动识别数据源（环境变量 / 运行时上下文）
- 高性能：JSONPath 缓存 + 扁平字典结构
- 零学习成本：开箱即用

使用示例：
    from framework.commons.resolver.placeholder import PlaceholderResolver

    resolver = PlaceholderResolver()

    # 配置中心场景（自动从环境变量读取）
    host = resolver.resolve("${DATABASES_DEFAULT_HOST:-localhost}")

    # JSONPath 场景（传入上下文）
    state = {'variables': {'start': {'city': '北京'}}}
    city = resolver.resolve("${variables.start.city}")
    city = resolver.resolve("${start.city}", context=state)

    # 递归解析字典
    config = resolver.resolve_dict(raw_config, context=state)
"""
import json
import os
import re
from typing import Any, cast
from urllib.parse import quote_plus

from jsonpath_ng import parse  # type: ignore[import-untyped]

from framework.commons.crypto import CryptoUtils
from framework.commons.logger import get_logger

logger = get_logger(__name__)


class PlaceholderResolver:
    """
    通用占位符解析器

    支持语法：
    - ${VAR}                    # 简单变量
    - ${VAR:-default}           # 带默认值
    - ${nested.path}            # 嵌套访问（工作流场景）

    工作原理：
    1. 配置中心：从 os.environ 查找（扁平字典）
    2. 工作流：从 context 字典查找（支持深层嵌套）
    3. 使用 JSONPath 递归搜索，无论层级多深都能找到
    """

    # 匹配模式：${VAR} 或 ${VAR:-default} 或 ${ENC:encrypted}
    PATTERN = re.compile(r'\$\{((?:ENC:)?[^}:]+)(?::-([^}]*))?\}')

    def __init__(self, env: dict[str, str] | None = None):
        """
        初始化解析器

        Args:
            env: 环境变量字典，默认为 os.environ
        """
        # 保持扁平结构，不进行嵌套转换
        self.env_dict = {
            key: value
            for key, value in (env or os.environ).items()
            if not key.startswith('_') and key not in ('PWD', 'SHLVL')
        }

        # JSONPath 表达式缓存
        self._cache: dict[str, Any] = {}

    def resolve(self, template: str, context: dict[str, Any] | None = None, preserve_type: bool = False) -> Any:
        """
        解析单个占位符

        Args:
            template: 包含占位符的模板字符串
            context: 上下文数据（工作流场景必需，配置中心可选）
            preserve_type: 是否保留原始类型（False=始终返回字符串，True=保留 dict/list 等类型）

        Returns:
            解析后的值
        """
        if not isinstance(template, str) or '${' not in template:
            return template

        # preserve_type=True 且模板只包含一个占位符时，直接返回解析后的值
        if preserve_type:
            match = self.PATTERN.fullmatch(template.strip())
            if match:
                return self._resolve_single_placeholder(match, context)

        # 原有逻辑：使用 re.sub 进行替换（返回字符串）
        return self.PATTERN.sub(
            lambda m: self._replace_match_str(m, context), template
        )

    def _resolve_single_placeholder(self, match: re.Match[str], context: dict[str, Any] | None) -> Any:
        """解析单个占位符，保留原始类型。"""
        var_path = match.group(1).strip()
        default_value = match.group(2) if match.group(2) is not None else None

        enc_result = self._try_decrypt(var_path, default_value)
        if enc_result is not None:
            return enc_result

        data_source = context if context is not None else self.env_dict
        value = self._lookup_value(var_path, data_source)

        if value is not None:
            if self._is_password_field(var_path):
                return quote_plus(str(value))
            return value
        return default_value

    def _replace_match_str(self, match: re.Match[str], context: dict[str, Any] | None) -> str:
        """替换匹配的占位符为字符串。"""
        var_path = match.group(1).strip()
        default_value = match.group(2) if match.group(2) is not None else ''

        enc_result = self._try_decrypt(var_path, default_value)
        if enc_result is not None:
            # _try_decrypt 返回 Any（CryptoUtils.decrypt + default_value 均为 Any），
            # 此处已排除 None，解密结果为字符串，用 cast 断言为 str
            return cast(str, enc_result)

        data_source = context if context is not None else self.env_dict
        value = self._lookup_value(var_path, data_source)

        if value is not None:
            if self._is_password_field(var_path):
                return quote_plus(str(value))
            if isinstance(value, (dict, list)):
                return json.dumps(value, ensure_ascii=False, default=str)
            return str(value)
        return default_value

    def _try_decrypt(self, var_path: str, default_value: Any) -> Any:
        """尝试解密 ENC: 前缀的值，非加密值返回 None。"""
        if not var_path.startswith('ENC:'):
            return None
        encrypted_value = var_path[4:].strip()
        try:
            return CryptoUtils.decrypt(encrypted_value)
        except Exception as e:
            logger.warning(f"解密失败: {e}")
            return default_value

    def _lookup_value(self, var_path: str, data_source: dict[str, Any]) -> Any:
        """通过 JSONPath 查找变量值。"""
        jsonpath_expr = f'$.{var_path}'
        value = self._jsonpath_search(jsonpath_expr, data_source)
        logger.debug(f"解析 {var_path} 为 {value}")
        return value

    @staticmethod
    def _is_password_field(var_path: str) -> bool:
        """判断变量路径是否为密码字段。"""
        return 'PASSWORD' in var_path.upper() or 'PASSWD' in var_path.upper()

    def resolve_dict(self, data: Any, context: dict[str, Any] | None = None) -> Any:
        """
        递归解析数据结构中的占位符

        Args:
            data: 待解析的数据结构（dict/list/str）
            context: 上下文数据（工作流场景）

        Returns:
            解析后的数据结构

        Examples:
            >>> resolver = PlaceholderResolver()
            >>> config = {
            ...     "database": {
            ...         "host": "${DB_HOST:-localhost}",
            ...         "port": "${DB_PORT:-5432}"
            ...     }
            ... }
            >>> resolver.resolve_dict(config)
            {'database': {'host': 'localhost', 'port': '5432'}}
        """
        if isinstance(data, dict):
            return {
                key: self.resolve_dict(value, context)
                for key, value in data.items()
            }
        elif isinstance(data, list):
            return [self.resolve_dict(item, context) for item in data]
        elif isinstance(data, str):
            return self.resolve(data, context)
        else:
            # 保持原始类型（int, bool, float, None）
            return data

    def _jsonpath_search(self, jsonpath_expr: str, data: dict) -> Any:
        """
        执行 JSONPath 搜索（带缓存）

        Args:
            jsonpath_expr: JSONPath 表达式
            data: 待搜索的数据

        Returns:
            第一个匹配的值，或 None
        """
        # 检查缓存
        if jsonpath_expr not in self._cache:
            try:
                self._cache[jsonpath_expr] = parse(jsonpath_expr)
            except Exception as e:
                logger.warning(f"JSONPath 解析失败: {jsonpath_expr}, 错误: {e}")
                return None

        expr = self._cache[jsonpath_expr]

        try:
            matches = expr.find(data)
            return matches[0].value if matches else None
        except Exception as e:
            logger.warning("JSONPath 查询失败: %s, 错误: %s", jsonpath_expr, e, exc_info=True)
            return None
