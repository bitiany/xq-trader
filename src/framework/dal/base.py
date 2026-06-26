"""
SQLAlchemy ORM 基类
包含通用 CRUD 方法

Base: 纯粹的 ORM 基类，仅提供数据源绑定和工具方法
AuditedBase: 继承 Base，增加 id / created_at / updated_at 审计字段
"""
import logging
from typing import Any, TypeVar, cast

from sqlalchemy import (
    DateTime,
    Integer,
    UniqueConstraint,
    and_,
    delete,
    func,
    or_,
    select,
)
from sqlalchemy import String as SaString
from sqlalchemy import func as sql_func
from sqlalchemy import (
    update as sql_update,
)
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy.sql.schema import Table
from typing_extensions import Self

from framework.commons.exceptions import DatasourceNotInitializedError

T = TypeVar('T', bound='Base')

logger = logging.getLogger("DATASOURCE.METHOD")


class Base(DeclarativeBase):
    """
    支持多数据源绑定的 ORM 基类

    仅提供数据源绑定和工具方法，不包含审计字段。

    使用方式:
        class User(Base):
            __bind_key__ = "default"
            __tablename__ = "users"
    """

    __bind_key__: str | None = None

    @classmethod
    def _get_engines_manager(cls) -> Any:
        """获取 engines_manager 单例（延迟导入，避免循环依赖）"""
        from framework.dal.enginee import engines_manager
        return engines_manager

    # ==================== 工具方法 ====================
    def to_dict(self) -> dict[str, Any]:
        """转换为字典（用于序列化）"""
        return {
            column.key: getattr(self, column.key)
            for column in cast(Table, self.__table__).columns
        }

    def update_from_dict(self, data: dict[str, Any]) -> Self:
        """
        从字典更新对象属性

        Args:
            data: 包含要更新的字段和值的字典

        Returns:
            更新后的对象本身（支持链式调用）
        """
        for key, value in data.items():
            if hasattr(self, key):
                setattr(self, key, value)
        return self

    # ==================== 类方法 - 查询操作 ====================
    @classmethod
    def _get_bind_key(cls) -> str:
        """获取当前模型的 bind_key（用于自动 session 管理）"""
        return getattr(cls, '__bind_key__', 'default') or 'default'

    @classmethod
    def _get_pk_value(cls, instance: "Base") -> Any | None:
        """获取实例的主键值，支持复合主键"""
        table = cast(Table, instance.__table__)
        pk_columns = list(table.primary_key.columns)
        if len(pk_columns) == 1:
            value = getattr(instance, pk_columns[0].name, None)
            return value
        values = tuple(getattr(instance, col.name, None) for col in pk_columns)
        if any(v is None for v in values):
            return None
        return values

    @classmethod
    def _get_pk_columns(cls) -> list[Any]:
        """获取所有主键列对象列表"""
        return list(cast(Table, cls.__table__).primary_key.columns)

    @classmethod
    def _get_pk_column(cls) -> Any:
        """获取第一个主键列对象（向后兼容）"""
        return list(cast(Table, cls.__table__).primary_key.columns)[0]

    @classmethod
    async def get(cls: type[T], id: Any) -> T | None:
        async with cls._get_engines_manager().get_transaction_session(
            cls._get_bind_key()
        ) as db:
            return cast(T | None, await db.get(cls, id))

    @classmethod
    async def get_by_id(cls: type[T], id: Any) -> T | None:
        return await cls.get(id)

    @classmethod
    def _build_filter_conditions(cls, **filters: Any) -> list[Any]:
        """
        构建过滤条件（支持 Tortoise-ORM 风格）

        支持的语法：
        - field=value: 等于
        - field__in=[v1, v2]: IN 查询
        - field__like='%value%': LIKE 模糊查询
        - field__gt=value: 大于
        - field__gte=value: 大于等于
        - field__lt=value: 小于
        - field__lte=value: 小于等于
        - field__ne=value: 不等于

        特殊处理：
        - 如果值为 None、空字符串、空列表，则忽略该条件
        - field__in=[]: 自动忽略（不添加IN条件）

        Returns:
            SQLAlchemy where 条件列表
        """
        conditions = []

        for key, value in filters.items():
            # 跳过空值条件
            if value is None:
                continue
            if isinstance(value, str) and value.strip() == '':
                continue
            if isinstance(value, (list, tuple)) and len(value) == 0:
                continue

            if '__' in key:
                field_name, operator = key.rsplit('__', 1)
                column = getattr(cls, field_name, None)

                if column is None:
                    continue

                if operator == 'in':
                    # IN 查询：确保列表非空
                    if isinstance(value, (list, tuple)) and len(value) > 0:
                        conditions.append(column.in_(value))
                elif operator == 'like':
                    conditions.append(column.like(value))
                elif operator == 'ilike':
                    conditions.append(column.ilike(value))
                elif operator == 'gt':
                    conditions.append(column > value)
                elif operator == 'gte':
                    conditions.append(column >= value)
                elif operator == 'lt':
                    conditions.append(column < value)
                elif operator == 'lte':
                    conditions.append(column <= value)
                elif operator == 'ne':
                    conditions.append(column != value)
            else:
                # 简单等值查询
                column = getattr(cls, key, None)
                if column is not None:
                    conditions.append(column == value)

        return conditions

    @classmethod
    async def filter(
        cls: type[T],
        skip: int = 0,
        limit: int | None = None,
        order_by: Any | None = None,
        **filters: Any,
    ) -> list[T]:
        """
        根据条件过滤记录（事务感知，支持 Tortoise-ORM 风格）

        Args:
            skip: 跳过记录数（分页）
            limit: 返回记录上限（分页）
            order_by: 排序字段，如 Model.created_at.desc()
            **filters: 过滤条件关键字参数

        Usage:
            # 简单过滤
            users = await User.filter(status=True)

            # IN 查询
            users = await User.filter(id__in=[1, 2, 3])

            # LIKE 模糊查询
            users = await User.filter(name__like='%john%')

            # 范围查询
            users = await User.filter(age__gte=18, age__lt=60)

            # 带分页
            users = await User.filter(skip=0, limit=10, status=True)

            # 带排序
            users = await User.filter(order_by=User.created_at.desc(), status=True)

            # 在事务中查询（保证快照一致性）
            @transactional()
            async def query_in_transaction():
                users = await User.filter(status=True)  # 自动加入当前事务
                return users
        """
        async with cls._get_engines_manager().get_transaction_session(
            cls._get_bind_key()
        ) as db:
            stmt = select(cls)

            # 构建过滤条件
            conditions = cls._build_filter_conditions(**filters)
            if conditions:
                stmt = stmt.where(and_(*conditions))

            # 添加排序
            if order_by is not None:
                if isinstance(order_by, (list, tuple)):
                    stmt = stmt.order_by(*order_by)
                else:
                    stmt = stmt.order_by(order_by)

            if skip > 0:
                stmt = stmt.offset(skip)
            if limit is not None and limit > 0:
                stmt = stmt.limit(limit)

            result = await db.execute(stmt)
            return list(result.scalars().all())

    @classmethod
    async def count_with_or(
        cls,
        or_conditions: list | None = None,
        and_filters: dict | None = None,
        *,
        or_groups: list[list] | None = None,
    ) -> int:
        """
        与 filter_with_or 一致的单表 COUNT（无 JOIN）。

        - or_conditions: 单层 OR；
        - or_groups: 多组 OR，组与组之间 AND（每组内 OR）。
        """
        async with cls._get_engines_manager().get_transaction_session(
            cls._get_bind_key()
        ) as db:
            pk_column = cls._get_pk_column()
            stmt = select(sql_func.count(pk_column))

            where_parts: list = []
            if or_groups:
                for grp in or_groups:
                    if grp:
                        where_parts.append(or_(*grp))
            elif or_conditions:
                where_parts.append(or_(*or_conditions))
            if and_filters:
                where_parts.extend(cls._build_filter_conditions(**and_filters))

            if where_parts:
                stmt = stmt.where(and_(*where_parts))

            result = await db.execute(stmt)
            return int(result.scalar() or 0)

    @classmethod
    async def filter_with_or(
        cls: type[T],
        or_conditions: list[Any] | None = None,
        and_filters: dict[str, Any] | None = None,
        skip: int = 0,
        limit: int = 100,
        order_by: Any | None = None,
        *,
        or_groups: list[list] | None = None,
    ) -> list[T]:
        """
        支持 OR 条件的过滤查询（事务感知）

        Args:
            or_conditions: OR 条件列表，如 [Model.name.like('%x%'), Model.code.like('%x%')]
            and_filters: AND 过滤条件字典，如 {'status': True}
            skip: 跳过记录数
            limit: 返回记录上限
            order_by: 排序字段

        Usage:
            from sqlalchemy import or_

            conditions = [
                User.name.like('%john%'),
                User.email.like('%john%')
            ]
            users = await User.filter_with_or(
                or_conditions=conditions,
                and_filters={'status': True},
                skip=0,
                limit=10
            )
        """
        async with cls._get_engines_manager().get_transaction_session(
            cls._get_bind_key()
        ) as db:
            stmt = select(cls)

            # 构建 WHERE 条件
            where_conditions = []

            # 添加 OR 条件
            if or_groups:
                for grp in or_groups:
                    if grp:
                        where_conditions.append(or_(*grp))
            elif or_conditions:
                where_conditions.append(or_(*or_conditions))

            # 添加 AND 条件
            if and_filters:
                and_conds = cls._build_filter_conditions(**and_filters)
                if and_conds:
                    where_conditions.extend(and_conds)

            # 应用所有条件
            if where_conditions:
                stmt = stmt.where(and_(*where_conditions))

            # 添加排序
            if order_by is not None:
                if isinstance(order_by, (list, tuple)):
                    stmt = stmt.order_by(*order_by)
                else:
                    stmt = stmt.order_by(order_by)

            # 添加分页
            if skip > 0:
                stmt = stmt.offset(skip)
            if limit > 0:
                stmt = stmt.limit(limit)

            result = await db.execute(stmt)
            return list(result.scalars().all())

    @classmethod
    async def get_or_none(cls: type[T], **filters: Any) -> T | None:
        async with cls._get_engines_manager().get_transaction_session(
            cls._get_bind_key()
        ) as db:
            stmt = select(cls).filter_by(**filters)
            result = await db.execute(stmt)
            return cast(T | None, result.scalar_one_or_none())

    @classmethod
    async def get_one_or_none(cls: type[T], **filters: Any) -> T | None:
        results = await cls.filter(limit=1, **filters)
        return results[0] if results else None

    @classmethod
    async def all(cls: type[T], **filters: Any) -> list[T]:
        """
        查询所有记录（可带过滤条件，自动获取 session）

        Usage:
            # 查询所有
            all_users = await User.all()

            # 带条件查询
            active_users = await User.all(status=True)
        """
        return await cls.filter(skip=0, limit=0, **filters)

    @classmethod
    async def count(cls, **filters: Any) -> int:
        """
        统计符合条件的记录数（事务感知）

        Usage:
            count = await User.count(status=True)

            # 在事务中统计
            @transactional()
            async def count_in_tx():
                count = await User.count(status=True)  # 自动加入事务
                return count
        """
        async with cls._get_engines_manager().get_transaction_session(
            cls._get_bind_key()
        ) as db:
            # 使用主键列进行统计（兼容不同主键名称）
            pk_column = cls._get_pk_column()
            stmt = select(sql_func.count(pk_column))

            conditions = cls._build_filter_conditions(**filters)
            if conditions:
                stmt = stmt.where(and_(*conditions))

            result = await db.execute(stmt)
            return result.scalar() or 0

    @classmethod
    async def update_by_id(cls: type[T], id: Any, data: dict[str, Any]) -> T | None:
        instance = await cls.get(id)
        if not instance:
            return None

        await instance.update(data)
        return instance

    @classmethod
    async def update_by(
        cls,
        data: dict[str, Any],
        **filters: Any,
    ) -> int:
        """
        根据条件批量更新指定字段（事务感知，支持 Tortoise-ORM 风格）

        使用 SQLAlchemy 的 UPDATE 语句直接执行，比逐条更新更高效。
        支持所有 Tortoise-ORM 风格的过滤条件：
        - field=value: 等值查询
        - field__in=[v1, v2]: IN 查询
        - field__like='%value%': LIKE 模糊查询
        - field__gt=value: 大于
        - field__gte=value: 大于等于
        - field__lt=value: 小于
        - field__lte=value: 小于等于
        - field__ne=value: 不等于

        Args:
            data: 包含要更新的字段和值的字典
            **filters: 过滤条件关键字参数

        Returns:
            更新的记录数

        Usage:
            # 简单更新
            count = await User.update_by(
                {"status": "active"},
                email="john@example.com"
            )

            # IN 查询更新
            count = await User.update_by(
                {"is_verified": True},
                id__in=[1, 2, 3]
            )

            # 组合条件更新
            count = await User.update_by(
                {"status": "expired"},
                status="pending",
                created_at__lt="2024-01-01"
            )

            # 在事务中更新
            @transactional()
            async def batch_update():
                count = await User.update_by(
                    {"last_login": datetime.now()},
                    last_login__lt="2023-01-01"
                )
                return count
        """
        try:
            async with cls._get_engines_manager().get_transaction_session(
                cls._get_bind_key()
            ) as db:
                # 构建更新语句
                stmt = sql_update(cls).values(**data)

                # 构建过滤条件
                conditions = cls._build_filter_conditions(**filters)
                if conditions:
                    stmt = stmt.where(and_(*conditions))

                # 执行批量更新
                result = await db.execute(stmt)
                updated_count = result.rowcount

                # flush 确保更新操作生效
                await db.flush()

                logger.debug(f"批量更新成功: {cls.__name__}, {updated_count} 条记录")
                return int(updated_count or 0)
        except Exception as e:
            logger.error(
                f"批量更新失败: {cls.__name__}, data={data}, filters={filters}, error={e}",
                exc_info=True
            )
            raise

    @classmethod
    async def delete_by_id(cls, id: Any) -> bool:
        """
        根据 ID 删除记录（自动获取 session）

        Args:
            id: 主键 ID

        Returns:
            True: 删除成功，False: 记录不存在

        Usage:
            success = await User.delete_by_id(1)
        """
        instance = await cls.get(id)
        if not instance:
            return False

        return await instance.delete()

    @classmethod
    async def delete_many(cls, **filters: Any) -> int:
        """
        根据条件批量删除记录（事务感知，支持 Tortoise-ORM 风格）

        使用 SQLAlchemy 的 DELETE 语句直接执行，比逐条删除更高效。
        支持所有 Tortoise-ORM 风格的过滤条件：
        - field=value: 等值查询
        - field__in=[v1, v2]: IN 查询
        - field__like='%value%': LIKE 模糊查询
        - field__gt=value: 大于
        - field__gte=value: 大于等于
        - field__lt=value: 小于
        - field__lte=value: 小于等于
        - field__ne=value: 不等于

        Args:
            **filters: 过滤条件关键字参数

        Returns:
            删除的记录数

        Usage:
            # 简单删除
            count = await User.delete_many(status='inactive')

            # IN 查询删除
            count = await User.delete_many(id__in=[1, 2, 3])

            # 组合条件删除
            count = await User.delete_many(
                status='pending',
                created_at__lt='2024-01-01'
            )

            # 在事务中删除
            @transactional()
            async def cleanup():
                count = await User.delete_many(status='deleted')
                return count
        """
        try:
            async with cls._get_engines_manager().get_transaction_session(
                cls._get_bind_key()
            ) as db:
                # 构建删除语句
                stmt = delete(cls)

                # 构建过滤条件
                conditions = cls._build_filter_conditions(**filters)
                if conditions:
                    stmt = stmt.where(and_(*conditions))

                # 执行批量删除
                result = await db.execute(stmt)
                deleted_count = result.rowcount

                # flush 确保删除操作生效
                await db.flush()

                logger.debug(f"批量删除成功: {cls.__name__}, {deleted_count} 条记录")
                return int(deleted_count or 0)
        except Exception as e:
            logger.error(
                f"批量删除失败: {cls.__name__}, filters={filters}, error={e}",
                exc_info=True
            )
            raise

    # ==================== 类方法 - 创建操作 ====================
    @classmethod
    async def create(cls: type[T], **kwargs: Any) -> T:
        """
        创建并保存新记录（自动获取 session）

        Args:
            **kwargs: 模型字段关键字参数

        Returns:
            创建后的对象（已 flush 和 refresh）

        Usage:
            user = await User.create(username="john", email="john@example.com")
        """
        instance = cls(**kwargs)
        return await cls.save(instance)

    # ==================== 实例方法 - 保存/更新操作 ====================

    async def save(self) -> Self:
        """
        保存或更新对象（事务感知）

        Returns:
            保存后的对象（已 flush 和 refresh）

        Usage:
            # 在事务装饰器中使用
            from framework.data.transaction import transactional

            @transactional()
            async def create_user():
                user = User(username="john")
                await user.save()  # 自动加入当前事务

            # 编程式事务
            from framework.data.transaction import transaction_manager

            async with transaction_manager.transaction():
                user = User(username="john")
                await user.save()
                await transaction_manager.commit()

            # 非事务环境（向后兼容）
            user = User(username="john")
            await user.save()  # 自动创建临时 session
        """
        # 使用事务感知的 session 获取方式
        async with self.__class__._get_engines_manager().get_transaction_session(
            self._get_bind_key()
        ) as db:
            # 检查主键值来判断是插入还是更新
            pk_value = self.__class__._get_pk_value(self)
            is_insert = pk_value is None
            if not is_insert:
                # 使用 SELECT ... FOR UPDATE 加行锁，防止并发 UPDATE 导致 lost update
                # 场景：高并发成交回报、双花板同时下单、KillSwitch 与正常流程并发等。
                # 行锁在事务内持有至 commit/rollback，临时 session 在退出时自动 commit 释放。
                pk_columns = list(cast(Table, self.__class__.__table__).primary_key.columns)
                if len(pk_columns) == 1:
                    stmt = select(self.__class__).where(
                        pk_columns[0] == pk_value
                    ).with_for_update()
                else:
                    # 复合主键：pk_value 为 tuple（is_insert=False 保证非 None）
                    pk_tuple = cast(tuple[Any, ...], pk_value)
                    stmt = select(self.__class__).where(
                        and_(*[col == val for col, val in zip(pk_columns, pk_tuple)])
                    ).with_for_update()
                result = await db.execute(stmt)
                existing = result.scalar_one_or_none()
                is_insert = existing is None

            if is_insert:
                # 新记录，执行插入
                # db.add 将 self 加入 session（pending），flush 后变为 persistent，可直接 refresh
                db.add(self)
                await db.flush()
                # refresh 加载 server_default 生成的字段（如自增主键 id、created_at）
                await db.refresh(self)
                return self

            # UPDATE 分支：记录已存在，执行更新（merge）
            # merge 返回 persistent 对象：
            #   - 事务内 self 已 persistent：返回 self
            #   - 事务外 self 是 detached：返回 identity map 中的新对象（非 self）
            merged = await db.merge(self)
            await db.flush()
            # refresh 加载 onupdate 生成的字段（如 updated_at）。
            # 关键：必须在 flush 之后 refresh，此时 DB 已包含 merge 写入的新值。
            # 若不 refresh，flush 后 updated_at 等字段处于 expired 状态，
            # sync getattr（如 to_dict）会触发 lazy load → greenlet_spawn 错误。
            await db.refresh(merged)
            # 事务外 self 是 detached，refresh(self) 会失败；
            # 因此 refresh merged（一定是 persistent），再同步属性到 self。
            # merged 刚被 refresh，属性非 expired，sync getattr 安全。
            if merged is not self:
                for column in cast(Table, self.__table__).columns:
                    setattr(self, column.key, getattr(merged, column.key))
            return self

    async def update(self, data: dict[str, Any]) -> Self:
        """
        更新对象并保存（依赖外部事务管理）

        Args:
            data: 包含要更新的字段和值的字典

        Returns:
            更新后的对象（已 flush 和 refresh）

        Usage:
            from framework.data.transaction import transactional

            @transactional()
            async def update_user():
                user = await User.get(1)
                await user.update({"username": "new_name"})
        """
        self.update_from_dict(data)
        return await self.save()

    # ==================== 类方法 - 批量操作 ====================

    @classmethod
    async def bulk_create_or_update(
        cls,
        instances: list[Self],
        on_conflict: list[str] | None = None,
        update_fields: list[str] | None = None,
        batch_size: int = 500
    ) -> int:
        """
        批量插入或更新记录（Upsert，事务感知，支持分片处理）

        基于 PostgreSQL 的 ON CONFLICT 语法实现高效的批量 upsert。
        API 设计参考 Tortoise-ORM 的 bulk_create() 方法。

        针对大数据量场景，自动进行分片处理，避免单次 SQL 过长。

        Args:
            instances: 待插入或更新的实例列表
            on_conflict: 冲突检测字段列表（唯一约束字段）
                        - None: 使用主键 (id) 作为冲突检测字段
                        - ['field1']: 单字段唯一键
                        - ['field1', 'field2']: 复合唯一键
            update_fields: 冲突时需要更新的字段列表
                          - None: 更新除主键和审计字段外的所有字段
                          - ['field1', 'field2']: 只更新指定字段
            batch_size: 分片大小，默认 500
                       - 小数据量 (< 500): 不分片，一次性处理
                       - 中等数据量 (500-5000): 分片处理，每批 500 条
                       - 大数据量 (> 5000): 分片处理，可调整 batch_size

        Returns:
            插入或更新成功的总数

        Usage:
            # 示例1：小数据量，不分片
            users = [
                User(id=1, username="john", email="john@example.com"),
                User(id=2, username="jane", email="jane@example.com"),
            ]
            count = await User.bulk_create_or_update(users)

            # 示例2：使用业务唯一键
            stocks = [
                Stock(symbol="600519.SH", open=1800.0, close=1820.0),
                Stock(symbol="000858.SZ", open=150.0, close=152.0),
            ]
            count = await Stock.bulk_create_or_update(
                stocks,
                on_conflict=["symbol"],
                update_fields=['open', 'close']
            )

            # 示例3：大数据量，自定义分片大小
            large_dataset = [...]  # 10000+ 条记录
            count = await Security.bulk_create_or_update(
                large_dataset,
                on_conflict=['id'],
                batch_size=1000  # 每批 1000 条
            )
        """
        if not instances:
            return 0

        total_count = len(instances)

        # 小数据量不分片，直接处理
        if total_count <= batch_size:
            return await cls._execute_batch_upsert(
                instances, on_conflict, update_fields
            )

        # 大数据量分片处理：在外层获取一次 session，所有批次复用
        async with cls._get_engines_manager().get_transaction_session(
            cls._get_bind_key()
        ) as db:
            total_processed = 0
            total_batches = (total_count + batch_size - 1) // batch_size

            logger.debug(
                f"开始分片批量 upsert: {cls.__name__}, "
                f"总计 {total_count} 条，分 {total_batches} 批，每批 {batch_size} 条"
            )

            for i in range(0, total_count, batch_size):
                batch = instances[i:i + batch_size]
                batch_num = i // batch_size + 1

                try:
                    batch_processed = await cls._execute_batch_upsert_with_session(
                        batch, on_conflict, update_fields, db
                    )

                    total_processed += batch_processed

                    # logger.debug(
                    #     f"批次 {batch_num}/{total_batches} 完成: "
                    #     f"处理 {batch_processed} 条记录"
                    # )

                except Exception as e:
                    first_row = {}
                    if batch:
                        inst = batch[0]
                        for col in cls.__table__.columns:
                            if col.autoincrement is True:
                                continue
                            v = getattr(inst, col.name, None)
                            if v is not None:
                                first_row[col.name] = str(v)[:100]
                    logger.error(
                        f"批次 {batch_num}/{total_batches} 处理失败 "
                        f"(batch_size={len(batch)}, first_row={first_row}): {e}",
                        exc_info=True
                    )
                    await db.rollback()
                    raise

            # 所有批次成功，提交事务
            await db.commit()
            return total_processed

    @classmethod
    async def _execute_batch_upsert(
        cls,
        instances: list[Self],
        on_conflict: list[str] | None = None,
        update_fields: list[str] | None = None
    ) -> int:
        """
        执行单批次 upsert 操作（内部方法，自动管理 session）

        Args:
            instances: 当前批次的实例列表
            on_conflict: 冲突检测字段
            update_fields: 更新字段列表

        Returns:
            处理的记录数
        """
        async with cls._get_engines_manager().get_transaction_session(
            cls._get_bind_key()
        ) as db:
            return await cls._execute_batch_upsert_with_session(
                instances, on_conflict, update_fields, db
            )

    @classmethod
    async def _execute_batch_upsert_with_session(
        cls,
        instances: list[Self],
        on_conflict: list[str] | None = None,
        update_fields: list[str] | None = None,
        db: AsyncSession | None = None,
    ) -> int:
        """执行单批次 upsert 操作（使用指定的 session）。"""
        table = cast(Table, cls.__table__)

        conflict_columns = on_conflict or [col.name for col in table.primary_key.columns]
        update_columns = cls._resolve_update_columns(table, conflict_columns, update_fields)
        values_list = cls._build_upsert_values(table, instances)

        if not values_list:
            return 0

        stmt = cls._build_upsert_stmt(table, values_list, conflict_columns, update_columns)

        if db is None:
            raise DatasourceNotInitializedError("db session is required for upsert")
        result = await db.execute(stmt)

        rowcount = getattr(result, "rowcount", None)
        return int(rowcount) if rowcount else len(instances)

    @classmethod
    def _resolve_update_columns(
        cls,
        table: Table,
        conflict_columns: list[str],
        update_fields: list[str] | None,
    ) -> list[str]:
        """确定 upsert 时需要更新的字段列表。"""
        if update_fields is not None:
            return update_fields
        exclude_fields = set(conflict_columns + ['created_at'])
        for col in table.primary_key.columns:
            exclude_fields.add(col.name)
        return [col.name for col in table.columns if col.name not in exclude_fields]

    @classmethod
    def _build_upsert_values(cls, table: Table, instances: list[Self]) -> list[dict[str, Any]]:
        """构建 upsert 的批量插入数据。"""
        values_list: list[dict[str, Any]] = []
        for instance in instances:
            row_data: dict[str, Any] = {}
            for col in table.columns:
                if col.autoincrement is True:
                    continue
                value = getattr(instance, col.name, None)
                if col.server_default is not None and value is None:
                    continue
                row_data[col.name] = value
            values_list.append(row_data)
        return values_list

    @classmethod
    def _build_upsert_stmt(
        cls,
        table: Table,
        values_list: list[dict[str, Any]],
        conflict_columns: list[str],
        update_columns: list[str],
    ) -> Any:
        """构建 PostgreSQL UPSERT 语句。"""
        stmt = pg_insert(table).values(values_list)
        set_ = {col: getattr(stmt.excluded, col) for col in update_columns}

        has_string_conflict = any(
            isinstance(table.c.get(cn).type, SaString)  # type: ignore[union-attr]
            for cn in conflict_columns
            if table.c.get(cn) is not None
        )

        if has_string_conflict:
            constraint_name = cls._find_unique_constraint_name(table, conflict_columns)
            if constraint_name:
                return stmt.on_conflict_do_update(constraint=constraint_name, set_=set_)

        return stmt.on_conflict_do_update(index_elements=conflict_columns, set_=set_)

    @classmethod
    def _find_unique_constraint_name(cls, table: Table, conflict_columns: list[str]) -> str | None:
        """查找匹配冲突字段的唯一约束名称。"""
        pk_constraint = table.primary_key
        if pk_constraint.name:
            return str(pk_constraint.name)
        for uc in table.constraints:
            if isinstance(uc, UniqueConstraint) and uc.name:
                uc_cols = {c.name for c in uc.columns}
                if uc_cols == set(conflict_columns):
                    return str(uc.name)
        return None

    @classmethod
    async def bulk_update(
        cls: type[T],
        updates: list[tuple[int, dict[str, Any]]]
    ) -> list[T]:
        """
        批量更新记录（事务感知）

        Args:
            updates: 元组列表，每个元组包含 (id, 更新数据)

        Returns:
            更新后的实例列表

        Usage:
            updates = [(1, {"status": True}), (2, {"status": False})]
            updated_users = await User.bulk_update(updates)
        """
        async with cls._get_engines_manager().get_transaction_session(
            cls._get_bind_key()
        ) as db:
            updated_instances = []
            for id_, data in updates:
                instance = await cls.get(id_)
                if instance:
                    instance.update_from_dict(data)
                    await db.flush()
                    await db.refresh(instance)
                    updated_instances.append(instance)

            return updated_instances

    async def delete(self) -> bool:
        """
        删除对象（事务感知）

        Usage:
            from framework.data.transaction import transactional

            @transactional()
            async def delete_user():
                user = await User.get(1)
                await user.delete()
        """
        # 使用事务感知的 session 获取方式
        async with self.__class__._get_engines_manager().get_transaction_session(
            self._get_bind_key()
        ) as db:
            pk_value = self.__class__._get_pk_value(self)
            if pk_value is not None:
                await db.delete(self)
                await db.flush()
                return True
            return False

    async def refresh(self) -> Self:
        """
        从数据库刷新对象数据（事务感知）

        Usage:
            from framework.data.transaction import transactional

            @transactional()
            async def refresh_user():
                user = await User.get(1)
                # ... 其他操作 ...
                await user.refresh()
        """
        # 使用事务感知的 session 获取方式
        async with self.__class__._get_engines_manager().get_transaction_session(
            self._get_bind_key()
        ) as db:
            await db.refresh(self)
            return self

class AuditedBase(Base):
    """
    带审计字段的 ORM 基类

    继承 Base，增加 id / created_at / updated_at 审计字段。

    使用方式:
        class User(AuditedBase):
            __bind_key__ = "default"
            __tablename__ = "users"
    """

    __abstract__ = True

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True, index=True)
    created_at: Mapped[Any] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    updated_at: Mapped[Any] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

