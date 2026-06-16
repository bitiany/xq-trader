"""数据中心服务 — 聚合水位、表统计、采集任务信息，为前端概览页和任务页提供数据。"""

from __future__ import annotations

import json
from collections import defaultdict
from datetime import date, datetime
from pathlib import Path
from typing import Any

import yaml
from sqlalchemy import text

from framework.commons.logger import get_logger
from framework.commons.pagination import build_paginated_response
from framework.config.settings import settings
from framework.dal.enginee import engines_manager
from xqtrader.domain.data.services.registries import DataTypeRegistry, TableRegistry
from xqtrader.domain.watermark.models.collect_watermark import CollectWatermark
from xqtrader.domain.watermark.models.trade_calendar import TradeCalendar
from xqtrader.domain.watermark.services.watermark_service import WatermarkService

logger = get_logger(__name__)


def _load_plugin_manifests() -> dict[str, dict[str, Any]]:
    """扫描插件目录，解析 plugin.yaml，返回 celery_task_name → manifest 映射。"""
    plugins_dir = Path(__file__).parent.parent.parent.parent.parent / "worker" / "plugins"
    if not plugins_dir.exists():
        return {}

    manifests: dict[str, dict[str, Any]] = {}
    for plugin_dir in sorted(plugins_dir.iterdir()):
        if not plugin_dir.is_dir() or plugin_dir.name.startswith("_"):
            continue
        yaml_path = plugin_dir / "plugin.yaml"
        if not yaml_path.exists():
            continue
        try:
            with open(yaml_path, encoding="utf-8") as f:
                data = yaml.safe_load(f) or {}
            task_name = data.get("celery_task_name", "")
            if task_name:
                data["_module_path"] = f"worker.plugins.{plugin_dir.name}"
                manifests[task_name] = data
        except Exception:
            logger.warning("解析 plugin.yaml 失败: %s", yaml_path, exc_info=True)

    return manifests


class DataService:
    """数据中心服务 — 聚合水位、表统计、采集任务信息。

    职责：
    1. 数据概览摘要（数据类型数、标的数、记录数、存储占用）
    2. 水位概览（按数据类型聚合水位统计）
    3. 数据表统计（PostgreSQL 系统表查询）
    4. 采集任务列表（从插件注册表 + TaskDef + TaskExec 聚合）
    5. 任务触发、日志查询、节点查询
    """

    def __init__(self) -> None:
        self._watermark_service = WatermarkService()

    # ── 数据概览 ──

    async def get_summary(self) -> dict[str, Any]:
        """数据概览摘要。"""
        watermarks = await CollectWatermark.filter(status="active")
        data_types: set[str] = set()
        watermark_codes: set[str] = set()
        total_records = 0
        for wm in watermarks:
            data_types.add(wm.data_type)
            watermark_codes.add(wm.watermark_code)
            total_records += wm.record_count

        tables = await self._query_table_stats()
        stock_table_count = len(tables)
        stock_total_bytes = sum(t["total_bytes"] for t in tables)

        worker_available = await self._check_worker_available()

        return {
            "data_type_count": len(data_types),
            "total_codes": len(watermark_codes),
            "total_records": total_records,
            "table_count": stock_table_count,
            "total_bytes": stock_total_bytes,
            "worker_available": worker_available,
        }

    async def get_watermarks(self) -> dict[str, Any]:
        """水位概览 — 按 data_type 聚合。"""
        ref_date = self._watermark_service.get_reference_date()
        latest_trade_date = await TradeCalendar.get_latest_trade_date(on_or_before=ref_date)

        watermarks = await CollectWatermark.filter(status="active")

        grouped: dict[str, list[CollectWatermark]] = defaultdict(list)
        for wm in watermarks:
            grouped[wm.data_type].append(wm)

        items: list[dict[str, Any]] = []
        for data_type, wm_list in sorted(grouped.items()):
            entry = DataTypeRegistry.get(data_type)
            code_count = len(wm_list)
            missing_count = sum(1 for wm in wm_list if wm.watermark_date is None)
            dates = [wm.watermark_date for wm in wm_list if wm.watermark_date is not None]
            min_date = str(min(dates)) if dates else None
            max_date = str(max(dates)) if dates else None
            total_records = sum(wm.record_count for wm in wm_list)

            coverage_pct = round((code_count - missing_count) / code_count * 100, 1) if code_count > 0 else None

            lag_days = None
            if latest_trade_date and max_date:
                max_d = date.fromisoformat(max_date) if isinstance(max_date, str) else max_date
                if max_d < latest_trade_date:
                    lag_days = await TradeCalendar.count_trading_days_after(max_d, latest_trade_date)

            items.append({
                "data_type": data_type,
                "display_name": entry.display_name,
                "display_name_en": entry.display_name_en,
                "code_count": code_count,
                "missing_count": missing_count,
                "min_date": min_date,
                "max_date": max_date,
                "total_records": total_records,
                "coverage_pct": coverage_pct,
                "lag_days": lag_days,
            })

        return {
            "reference_trade_date": str(latest_trade_date) if latest_trade_date else None,
            "items": items,
        }

    async def get_tables(self) -> list[dict[str, Any]]:
        """数据表统计 — 查询 PostgreSQL 系统表。"""
        rows = await self._query_table_stats()
        result: list[dict[str, Any]] = []
        for row in rows:
            entry = TableRegistry.get(row["table_name"])
            result.append({
                "schema_name": row["schema_name"],
                "table_name": row["table_name"],
                "label": entry.label,
                "label_en": entry.label_en,
                "approx_rows": row["approx_rows"],
                "total_size": row["total_size"],
                "total_bytes": row["total_bytes"],
            })
        return result

    async def get_overview(self) -> dict[str, Any]:
        """综合概览 — 一次返回摘要 + 水位 + 表统计（复用查询结果）。"""
        # 1. 一次查询水位数据，供摘要和水位概览共用
        watermarks = await CollectWatermark.filter(status="active")

        # 2. 一次查询表统计，供摘要和表列表共用
        table_rows = await self._query_table_stats()

        # 3. 构建摘要
        data_types: set[str] = set()
        watermark_codes: set[str] = set()
        total_records = 0
        for wm in watermarks:
            data_types.add(wm.data_type)
            watermark_codes.add(wm.watermark_code)
            total_records += wm.record_count

        table_count = len(table_rows)
        total_bytes = sum(t["total_bytes"] for t in table_rows)
        worker_available = await self._check_worker_available()

        # 4. 构建水位概览
        ref_date = self._watermark_service.get_reference_date()
        latest_trade_date = await TradeCalendar.get_latest_trade_date(on_or_before=ref_date)

        grouped: dict[str, list[CollectWatermark]] = defaultdict(list)
        for wm in watermarks:
            grouped[wm.data_type].append(wm)

        wm_items: list[dict[str, Any]] = []
        for data_type, wm_list in sorted(grouped.items()):
            entry = DataTypeRegistry.get(data_type)
            code_count = len(wm_list)
            missing_count = sum(1 for wm in wm_list if wm.watermark_date is None)
            dates = [wm.watermark_date for wm in wm_list if wm.watermark_date is not None]
            min_date = str(min(dates)) if dates else None
            max_date = str(max(dates)) if dates else None
            wm_total_records = sum(wm.record_count for wm in wm_list)

            coverage_pct = round((code_count - missing_count) / code_count * 100, 1) if code_count > 0 else None

            lag_days = None
            if latest_trade_date and max_date:
                max_d = date.fromisoformat(max_date) if isinstance(max_date, str) else max_date
                if max_d < latest_trade_date:
                    lag_days = await TradeCalendar.count_trading_days_after(max_d, latest_trade_date)

            wm_items.append({
                "data_type": data_type,
                "display_name": entry.display_name,
                "display_name_en": entry.display_name_en,
                "code_count": code_count,
                "missing_count": missing_count,
                "min_date": min_date,
                "max_date": max_date,
                "total_records": wm_total_records,
                "coverage_pct": coverage_pct,
                "lag_days": lag_days,
            })

        # 5. 构建表列表
        tables: list[dict[str, Any]] = []
        for row in table_rows:
            tbl_entry = TableRegistry.get(row["table_name"])
            tables.append({
                "schema_name": row["schema_name"],
                "table_name": row["table_name"],
                "label": tbl_entry.label,
                "label_en": tbl_entry.label_en,
                "approx_rows": row["approx_rows"],
                "total_size": row["total_size"],
                "total_bytes": row["total_bytes"],
            })

        return {
            "data_type_count": len(data_types),
            "total_codes": len(watermark_codes),
            "total_records": total_records,
            "table_count": table_count,
            "total_bytes": total_bytes,
            "worker_available": worker_available,
            "reference_trade_date": str(latest_trade_date) if latest_trade_date else None,
            "watermarks": wm_items,
            "tables": tables,
        }

    # ── 采集任务 ──

    async def get_tasks(self) -> list[dict[str, Any]]:
        """采集任务列表 — 从 plugin.yaml + TaskDef + TaskExec 聚合。"""
        from worker.models import TaskDef

        manifests = _load_plugin_manifests()
        task_defs = {td.name: td for td in await TaskDef.filter()}

        last_execs = await self._get_last_executions(list(manifests.keys()))

        worker_available = await self._check_worker_available()

        result: list[dict[str, Any]] = []
        for task_name, manifest_data in sorted(manifests.items()):
            task_def = task_defs.get(task_name)
            last_exec = last_execs.get(task_name)

            schedule = manifest_data.get("schedule") or None
            schedule_display = self._format_schedule(schedule) if schedule else ""
            schedule_display_en = self._format_schedule_en(schedule) if schedule else ""

            status = self._resolve_task_status(last_exec, getattr(task_def, "is_active", True))

            result.append({
                "task_id": task_name,
                "task_name": manifest_data.get("task_name") or manifest_data.get("name", ""),
                "task_name_en": manifest_data.get("task_name_en") or manifest_data.get("name", ""),
                "description": manifest_data.get("description", ""),
                "description_en": manifest_data.get("description_en") or manifest_data.get("description", ""),
                "category": manifest_data.get("category", "compute"),
                "task_type": manifest_data.get("task_type", "on_demand"),
                "is_scheduled": bool(schedule),
                "schedule": schedule,
                "schedule_display": schedule_display,
                "schedule_display_en": schedule_display_en,
                "queue": manifest_data.get("queue", "celery"),
                "timeout": manifest_data.get("timeout", 300),
                "params_schema": manifest_data.get("params_schema") or None,
                "enabled": task_def.is_active if task_def else True,
                "status": status,
                "last_run_at": last_exec.get("finished_at") if last_exec else None,
                "worker_available": worker_available,
                "source": manifest_data.get("_module_path", ""),
                "version": manifest_data.get("version", "1.0.0"),
            })

        return result

    async def trigger_task(self, task_id: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        """触发采集任务。"""
        manifests = _load_plugin_manifests()
        manifest_data = manifests.get(task_id)
        if manifest_data is None:
            from framework.commons.exceptions import NotFoundException
            raise NotFoundException(message=f"任务 {task_id} 不存在")

        from worker.celery_app import celery_app

        kwargs = params or {}
        queue = manifest_data.get("queue", "celery")
        celery_app.send_task(task_id, kwargs=kwargs, queue=queue)

        task_name = manifest_data.get("task_name") or task_id
        return {
            "task_id": task_id,
            "queued": True,
            "message": f"任务 {task_name} 已加入队列",
        }

    async def get_task_logs(
        self,
        task_id: str,
        level: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> dict[str, Any]:
        """获取任务执行日志。"""
        from worker.models import TaskExec

        filters: dict[str, Any] = {"task_name": task_id}
        if level:
            filters["level"] = level

        items = await TaskExec.filter(skip=offset, limit=limit, **filters)
        total = await TaskExec.count(**filters)

        log_items = []
        for item in items:
            log_items.append({
                "id": item.id,
                "task_id": item.task_name,
                "celery_task_id": item.id,
                "cycle_id": None,
                "node_id": None,
                "level": item.status,
                "message": item.result or "",
                "traceback": None,
                "extra": {"args": item.args} if item.args else None,
                "created_at": item.started_at,
            })

        return build_paginated_response(log_items, total, offset // limit + 1, limit)

    async def get_nodes(self) -> list[dict[str, Any]]:
        """获取工作节点信息。"""
        try:
            import asyncio  # noqa: I001
            from worker.celery_app import celery_app

            inspect = celery_app.control.inspect(timeout=3.0)
            stats = await asyncio.to_thread(inspect.stats)
            if not stats:
                return []

            result: list[dict[str, Any]] = []
            for node_name, node_stats in stats.items():
                result.append({
                    "node_id": node_name,
                    "status": "online",
                    "queues": list(node_stats.get("delivery_info", {}).keys()) if "delivery_info" in node_stats else [],
                    "last_heartbeat": datetime.now().isoformat(),
                })
            return result
        except Exception:
            logger.warning("获取工作节点信息失败", exc_info=True)
            return []

    # ── 编排管线 ──

    async def get_pipelines(self) -> list[dict[str, Any]]:
        """编排管线列表 — 从 schedules YAML + sch_pipeline_def 聚合。

        schedules/ 目录下每个 YAML 文件定义一个编排，
        sch_pipeline_def 中 type=dependent 的记录提供子步骤信息。
        """
        from worker.models import PipelineDef

        # 1. 从 YAML 文件加载编排定义
        pipelines_config = self._load_pipeline_yaml()

        # 2. 从 DB 获取子步骤和执行状态
        all_defs = await PipelineDef.filter()
        step_defs: dict[str, list[dict[str, Any]]] = {}
        for d in all_defs:
            config: dict[str, Any] = {}
            if d.config:
                try:
                    config = json.loads(d.config)
                except Exception:
                    config = {}

            if config.get("type") == "dependent":
                pn = config.get("pipeline_name", "")
                step_info: dict[str, Any] = {
                    "name": d.name,
                    "task": config.get("celery_task_name", ""),
                    "depends_on": config.get("depends_on", []),
                    "args": config.get("kwargs", {}),
                }
                step_defs.setdefault(pn, []).append(step_info)

        # 3. 聚合
        pipeline_names = list(pipelines_config.keys())
        last_execs = await self._get_last_executions(pipeline_names)

        result: list[dict[str, Any]] = []
        for pname, pcfg in pipelines_config.items():
            last_exec = last_execs.get(pname)
            steps = step_defs.get(pname, pcfg.get("steps", []))

            result.append({
                "pipeline_name": pname,
                "description": pcfg.get("description", ""),
                "mode": pcfg.get("mode", "canvas"),
                "cron": pcfg.get("cron"),
                "queue": pcfg.get("queue", "celery"),
                "enabled": pcfg.get("enabled", True),
                "steps": steps,
                "step_count": len(steps),
                "status": self._resolve_task_status(last_exec, pcfg.get("enabled", True)),
                "last_run_at": last_exec.get("finished_at") if last_exec else None,
            })

        return result

    @staticmethod
    def _load_pipeline_yaml() -> dict[str, dict[str, Any]]:
        """从 schedules/ 目录加载编排 YAML 配置。"""
        schedule_dir = Path(settings.APP.ROOT_DIR) / "schedules"
        if not schedule_dir.exists():
            return {}

        result: dict[str, dict[str, Any]] = {}
        for yml_file in sorted(schedule_dir.glob("*.yml")):
            try:
                with open(yml_file, encoding="utf-8") as f:
                    config = yaml.safe_load(f) or {}
            except Exception:
                logger.warning("解析编排配置失败: %s", yml_file, exc_info=True)
                continue

            if not config or "name" not in config or "steps" not in config:
                continue

            result[config["name"]] = config
        return result

    async def trigger_pipeline(self, pipeline_name: str) -> dict[str, Any]:
        """触发编排管线。"""
        pipelines_config = self._load_pipeline_yaml()
        if pipeline_name not in pipelines_config:
            from framework.commons.exceptions import NotFoundException
            raise NotFoundException(message=f"编排 {pipeline_name} 不存在")

        pcfg = pipelines_config[pipeline_name]
        queue = pcfg.get("queue", "celery")

        from worker.celery_app import celery_app

        celery_app.send_task(
            "worker.orchestration.trigger_pipeline",
            kwargs={"pipeline_name": pipeline_name},
            queue=queue,
        )

        return {
            "pipeline_name": pipeline_name,
            "queued": True,
            "message": f"编排 {pipeline_name} 已加入队列",
        }

    # ── 私有方法 ──

    async def _query_table_stats(self) -> list[dict[str, Any]]:
        """查询 PostgreSQL 系统表获取 stock schema 下的表统计信息。"""
        sql = text("""
            SELECT
                n.nspname AS schema_name,
                c.relname AS table_name,
                COALESCE(c.reltuples::bigint, 0) AS approx_rows,
                pg_size_pretty(pg_total_relation_size(c.oid)) AS total_size,
                COALESCE(pg_total_relation_size(c.oid), 0) AS total_bytes
            FROM pg_class c
            JOIN pg_namespace n ON n.oid = c.relnamespace
            WHERE n.nspname = 'stock'
                AND c.relkind = 'r'
                AND NOT c.relname LIKE '_hyper_%'
                AND NOT c.relname LIKE '_compressed_%'
            ORDER BY total_bytes DESC
        """)
        try:
            engine = engines_manager.get_engine("default")
            async with engine.begin() as conn:
                result = await conn.execute(sql)
                return [dict(row._mapping) for row in result.fetchall()]
        except Exception:
            logger.error("查询表统计信息失败", exc_info=True)
            return []

    async def _check_worker_available(self) -> bool:
        """检查 Celery Worker 是否在线。"""
        try:
            import asyncio  # noqa: I001
            from worker.celery_app import celery_app

            inspect = celery_app.control.inspect(timeout=3.0)
            active = await asyncio.to_thread(inspect.ping)
            return bool(active)
        except Exception:
            logger.warning("Worker 可用性检查失败", exc_info=True)
            return False

    async def _get_last_executions(self, task_names: list[str]) -> dict[str, dict[str, Any]]:
        """获取每个任务的最近一次执行记录（批量查询）。"""
        from worker.models import TaskExec

        result: dict[str, dict[str, Any]] = {}
        if not task_names:
            return result

        # 批量查询所有相关任务的执行记录，按 started_at 降序
        all_execs = await TaskExec.filter(
            task_name__in=task_names,
            order_by=TaskExec.started_at.desc(),
        )

        # 按 task_name 分组，取每组第一条（即最新）
        seen: set[str] = set()
        for ex in all_execs:
            if ex.task_name in seen:
                continue
            seen.add(ex.task_name)
            result[ex.task_name] = {
                "status": ex.status,
                "finished_at": ex.finished_at,
                "started_at": ex.started_at,
            }

        return result

    @staticmethod
    def _resolve_task_status(last_exec: dict[str, Any] | None, is_active: bool = True) -> str:
        """解析任务当前状态。"""
        if not is_active:
            return "disabled"
        if last_exec is None:
            return "idle"
        status = last_exec.get("status", "")
        if status == "SUCCESS":
            return "success"
        if status in ("FAILURE", "FAILED"):
            return "failed"
        return "idle"

    @staticmethod
    def _format_schedule(cron: str) -> str:
        """格式化 cron 表达式为中文显示。"""
        parts = cron.split()
        if len(parts) != 5:
            return cron
        minute, hour, day, month, weekday = parts
        if weekday != "*" and hour != "*" and minute != "*":
            days = {"1": "周一", "2": "周二", "3": "周三", "4": "周四", "5": "周五", "6": "周六", "0": "周日"}
            day_str = days.get(weekday, f"周{weekday}")
            return f"每{day_str} {hour}:{minute.zfill(2)}"
        if day == "*" and month == "*" and weekday == "*" and hour != "*" and minute != "*":
            return f"每天 {hour}:{minute.zfill(2)}"
        return cron

    @staticmethod
    def _format_schedule_en(cron: str) -> str:
        """格式化 cron 表达式为英文显示。"""
        parts = cron.split()
        if len(parts) != 5:
            return cron
        minute, hour, day, month, weekday = parts
        if weekday != "*" and hour != "*" and minute != "*":
            days = {"1": "Mon", "2": "Tue", "3": "Wed", "4": "Thu", "5": "Fri", "6": "Sat", "0": "Sun"}
            day_str = days.get(weekday, weekday)
            return f"Every {day_str} {hour}:{minute.zfill(2)}"
        if day == "*" and month == "*" and weekday == "*" and hour != "*" and minute != "*":
            return f"Daily {hour}:{minute.zfill(2)}"
        return cron
