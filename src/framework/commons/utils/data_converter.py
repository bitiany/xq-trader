"""
框架工具：DataFrame 到 ORM Model 的自动转换器
example:

# 列映射：Tushare 字段名到 Security 模型字段名
column_mapping = {
    'symbol': 'stock_code',  # stock_code -> Security.symbol
}

# 3. 自定义转换函数
custom_transforms = {
    'board_type': lambda x: self._parse_board_type(x['symbol']) if isinstance(x, dict) else '',
}

# 4. 转换 DataFrame 到 Security 实例
instances = DataFrameToModelConverter.convert(
    df=df,
    model_class=Security,
    column_mapping=column_mapping,
    custom_transforms=custom_transforms,
)

"""
from collections.abc import Callable
from datetime import date, datetime
from typing import Any, TypeVar

import pandas as pd
from sqlalchemy import Boolean, Date, DateTime, Float, Integer, Numeric, String
from sqlalchemy.orm import DeclarativeBase

from framework.commons.utils.date_utils import parse_date, parse_datetime

T = TypeVar('T', bound='DeclarativeBase')

class DataFrameToModelConverter:
    """
    将 Pandas DataFrame 自动转换为 SQLAlchemy ORM 模型实例列表
    """

    # SQLAlchemy 类型到 Python 类型的映射表
    TYPE_MAP = {
        String: str,
        Integer: int,
        Float: float,
        Numeric: float,
        Date: date,
        DateTime: datetime,
        Boolean: bool,
    }

    @classmethod
    def convert(
        cls,
        df: pd.DataFrame,
        model_class: type[T],
        custom_transforms: dict[str, Callable[[Any], Any]] | None = None,
        column_mapping: dict[str, str] | None = None
    ) -> list[T]:
        """
        执行转换
        """
        if df.empty:
            return []

        # 1. 获取模型字段信息 (基于 Column 元数据)
        model_fields = cls._get_model_fields(model_class)

        if not model_fields:
            print(f"Warning: No fields found for model {model_class.__name__}")
            return []

        # 2. 预处理 DataFrame (重命名列以匹配模型字段)
        work_df = df.copy()
        if column_mapping:
            # column_mapping: {model_field: df_column}
            reverse_mapping = {v: k for k, v in column_mapping.items()}
            existing_cols = {k: v for k, v in reverse_mapping.items() if k in work_df.columns}
            if existing_cols:
                work_df = work_df.rename(columns=existing_cols)

        instances = []

        # 3. 逐行转换
        for index, row in work_df.iterrows():
            instance_data = {}

            for field_name, field_info in model_fields.items():
                # 4. 应用自定义转换 (优先级最高)
                if custom_transforms and field_name in custom_transforms:
                    try:
                        # 如果字段在 DataFrame 中，使用其值；否则传入 None 让自定义转换处理默认值
                        raw_value = row[field_name] if field_name in work_df.columns else None
                        val = custom_transforms[field_name](raw_value)
                    except Exception:
                        # print(f"Custom transform error for {field_name}: {e}")
                        val = None
                elif field_name in work_df.columns:
                    # 5. 自动类型转换 (仅当字段在 DataFrame 中存在)
                    raw_value = row[field_name]
                    val = cls._auto_cast(raw_value, field_info['type'], field_info['nullable'])
                else:
                    # 字段不在 DataFrame 中，设置为 None
                    val = None

                instance_data[field_name] = val

            # 创建实例
            try:
                if instance_data:
                    instance = model_class(**instance_data)
                    instances.append(instance)
            except Exception as e:
                print(f"Warning: Failed to create instance for row index {index}: {e}")
                print(f"Data: {instance_data}")
                # 打印出错的字段类型，方便调试
                for k, v in instance_data.items():
                    if v is not None:
                        print(f"  Field '{k}' type: {type(v)}, value: {v}")

        return instances

    @staticmethod
    def _get_model_fields(model_class: type[T]) -> dict[str, dict]:
        """
        提取模型的字段名、类型和是否可空
        策略：直接解析 __table__.columns 中的 Column 对象
        """
        fields: dict[str, dict[str, Any]] = {}

        if not hasattr(model_class, '__table__'):
            return fields

        for col_name, col_obj in model_class.__table__.columns.items():
            # 忽略私有字段
            if col_name.startswith('_'):
                continue

            # 1. 确定 Python 类型
            py_type = DataFrameToModelConverter._map_sa_type_to_py(col_obj.type)

            # 2. 确定是否可空
            is_nullable = col_obj.nullable

            fields[col_name] = {
                'type': py_type,
                'nullable': is_nullable
            }

        return fields

    @staticmethod
    def _map_sa_type_to_py(sa_type: Any) -> type:
        """
        将 SQLAlchemy 类型映射为 Python 原生类型
        """
        # 遍历映射表，检查 sa_type 是否是某个基类的实例
        for sa_base, py_type in DataFrameToModelConverter.TYPE_MAP.items():
            if isinstance(sa_type, sa_base):
                return py_type

        # 默认返回 str
        return str

    @staticmethod
    def _auto_cast(value: Any, target_type: type, nullable: bool) -> Any:
        """
        自动类型转换核心逻辑
        """
        # 安全检查：避免 Series 传入
        if hasattr(value, '__len__') and hasattr(value, '__getitem__') and not isinstance(value, (str, bytes)):
            # 可能是 Series 或其他容器，取第一个元素或返回 None
            try:
                import pandas as pd
                if isinstance(value, pd.Series):
                    value = value.iloc[0] if len(value) > 0 else None
            except Exception:
                return None

        # 空值检查（安全调用）
        try:
            import pandas as pd
            if pd.isna(value):
                return None
        except (ValueError, TypeError):
            # pd.isna 对某些类型会报错，直接跳过
            pass

        if value is None:
            return None

        # 1. 日期处理
        if target_type == date:
            return DataFrameToModelConverter._parse_date(value)
        if target_type == datetime:
            return DataFrameToModelConverter._parse_datetime(value)

        # 2. 数值处理
        if target_type in (int, float):
            try:
                return target_type(value)
            except (ValueError, TypeError):
                return None

        # 3. 字符串处理
        if target_type is str:
            return str(value)

        # 4. 布尔处理
        if target_type is bool:
            if isinstance(value, str):
                return value.lower() in ('true', '1', 'yes')
            return bool(value)

        # 5. 其他类型直接返回
        return value

    @staticmethod
    def _parse_date(val: Any) -> date | None:
        return parse_date(val)

    @staticmethod
    def _parse_datetime(val: Any) -> datetime | None:
        return parse_datetime(val)
