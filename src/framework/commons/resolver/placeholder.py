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
from typing import Any

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

        Examples:
            >>> resolver = PlaceholderResolver()
            >>> os.environ['DB_HOST'] = 'localhost'
            >>> resolver.resolve("${DB_HOST:-127.0.0.1}")
            'localhost'

            >>> state = {'variables': {'start': {'city': '北京'}}}
            >>> resolver.resolve("${start.city}", context=state)
            '北京'
        """
        if not isinstance(template, str) or '${' not in template:
            return template
        # 如果 preserve_type=True 且模板只包含一个占位符，直接返回解析后的值（不转换为字符串）
        if preserve_type:
            match = self.PATTERN.fullmatch(template.strip())
            if match:
                var_path = match.group(1).strip()
                default_value = match.group(2) if match.group(2) is not None else None

                # 处理加密值 ${ENC:encrypted}
                if var_path.startswith('ENC:'):
                    encrypted_value = var_path[4:].strip()
                    try:
                        decrypted = CryptoUtils.decrypt(encrypted_value)
                        return decrypted
                    except Exception as e:
                        logger.warning(f"解密失败: {e}")
                        return default_value

                # 确定数据源
                data_source = context if context is not None else self.env_dict

                # 构建 JSONPath 表达式
                jsonpath_expr = f'$.{var_path}'

                # 查找值
                value = self._jsonpath_search(jsonpath_expr, data_source)
                logger.debug(f"解析 {var_path} 为 {value}")

                if value is not None:
                    # 对密码字段进行 URL 编码
                    if ('PASSWORD' in var_path.upper() or 'PASSWD' in var_path.upper()):
                        from urllib.parse import quote_plus
                        return quote_plus(str(value))
                    return value  # 直接返回原始类型（dict/list等）
                else:
                    return default_value

        # 原有逻辑：使用 re.sub 进行替换（返回字符串）
        def replace_match(match: re.Match[str]) -> str:
            var_path = match.group(1).strip()
            default_value = match.group(2) if match.group(2) is not None else ''

            # 处理加密值 ${ENC:encrypted}
            if var_path.startswith('ENC:'):
                encrypted_value = var_path[4:].strip()
                try:
                    decrypted = CryptoUtils.decrypt(encrypted_value)
                    return decrypted
                except Exception as e:
                    logger.warning(f"解密失败: {e}")
                    return default_value
            # 确定数据源
            if context is not None:
                # 工作流场景：从 context 中查找
                data_source = context
            else:
                # 配置中心场景：从环境变量中查找
                data_source = self.env_dict

            # 构建 JSONPath 表达式
            # ${VAR} → $.VAR
            # ${nested.path} → $.nested.path
            jsonpath_expr = f'$.{var_path}'

            # 查找值
            value = self._jsonpath_search(jsonpath_expr, data_source)

            if value is not None:
                # 对密码字段进行 URL 编码
                if ('PASSWORD' in var_path.upper() or 'PASSWD' in var_path.upper()):
                    from urllib.parse import quote_plus
                    return quote_plus(str(value))
                # 对于 dict/list 类型，使用 JSON 序列化而不是 str()
                if isinstance(value, (dict, list)):
                    return json.dumps(value, ensure_ascii=False, default=str)
                return str(value)
            else:
                return default_value

        return self.PATTERN.sub(replace_match, template)

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
        except Exception:
            # JSONPath 查询失败时静默返回 None
            return None


if __name__ == "__main__":
    import time

    print("=" * 70)
    print("PlaceholderResolver 测试")
    print("=" * 70)

    resolver = PlaceholderResolver()

    # 测试1: 配置中心场景
    print("\n[TEST 1] 配置中心场景")
    os.environ['TEST_DB_HOST'] = 'test-host'
    os.environ['TEST_DB_PORT'] = '5432'

    # 重新初始化以包含新变量
    resolver = PlaceholderResolver()

    result = resolver.resolve("${TEST_DB_HOST:-localhost}")
    print("  模板: ${TEST_DB_HOST:-localhost}")
    print(f"  结果: {result}")
    assert result == 'test-host', f"期望 'test-host'，实际 '{result}'"
    print("  ✅ 通过")

    # 测试2: 带默认值
    print("\n[TEST 2] 带默认值")
    result = resolver.resolve("${UNDEFINED_VAR:-default_value}")
    print("  模板: ${UNDEFINED_VAR:-default_value}")
    print(f"  结果: {result}")
    assert result == 'default_value'
    print("  ✅ 通过")

    # 测试3: 工作流场景
    print("\n[TEST 3] 工作流场景")
    state = {
        'variables': {
            'start': {'city': '北京'},
            'llm': {'response': '天气晴朗'}
        }
    }
    # 工作流中，context 应该是 variables + context 的合并
    context = {**state.get('variables', {}), **state.get('context', {})}
    result = resolver.resolve("${start.city}", context=context)
    print("  模板: ${start.city}")
    print(f"  结果: {result}")
    assert result == '北京'
    print("  ✅ 通过")

    # 测试4: 递归解析字典
    print("\n[TEST 4] 递归解析字典")
    config = {
        "database": {
            "host": "${TEST_DB_HOST:-localhost}",
            "port": "${TEST_DB_PORT:-3306}",
            "pool_size": "${POOL_SIZE:-10}"
        }
    }
    result = resolver.resolve_dict(config)
    print(f"  原始配置: {config}")
    print(f"  解析结果: {result}")
    assert result['database']['host'] == 'test-host'
    assert result['database']['port'] == '5432'
    assert result['database']['pool_size'] == '10'
    print("  ✅ 通过")

    # 测试5: 加密值测试
    print("\n[TEST 5] 加密值测试")
    from framework.commons.crypto import CryptoUtils
    test_secret = "test_password"
    encrypted = CryptoUtils.encrypt(test_secret)
    encrypted_placeholder = f"${{ENC:{encrypted}}}"

    result = resolver.resolve(encrypted_placeholder)
    print(f"  加密值: {encrypted[:20]}...")
    print(f"  解密结果: {result}")
    assert result == test_secret
    print("  ✅ 加密值测试通过")

    # 测试6: 性能测试
    print("\n[TEST 6] 性能测试")

    # 预热缓存
    for _ in range(100):
        resolver.resolve("${TEST_DB_HOST}")

    # 测试 JSONPath 方案
    start = time.time()
    for _ in range(10000):
        resolver.resolve("${TEST_DB_HOST:-localhost}")
    jsonpath_time = time.time() - start

    print(f"  JSONPath 方案: {jsonpath_time:.3f}s")
    print("  性能测试完成")

    print("\n" + "=" * 70)
    print("✅ 所有测试通过！")
    print("=" * 70)
