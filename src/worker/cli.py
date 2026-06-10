"""Worker CLI — 命令行工具，用于发送任务和管理分布式锁。

用法：
    python -m worker.cli run <task_name> [--symbols 000001.SZ,600519.SH] [--mode full] [--kwargs key=val]
    python -m worker.cli list
    python -m worker.cli lock-list
    python -m worker.cli lock-release <task_name>
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any


def _init_env() -> None:
    """初始化环境：加载 .env、注册数据源、发现插件。"""
    from framework.config.settings import settings
    from framework.dal.datasource_loader import DatasourceLoader
    from framework.dal.register import register_datasource_sync

    # 加载数据源
    loader = DatasourceLoader(settings.APP.DB_CONFIG_PATH)
    register_datasource_sync(loader.datasources)

    # 发现插件（注册 Celery task）
    from worker.plugin import autodiscover

    plugins_dir = str(Path(__file__).parent / "plugins")
    autodiscover(plugins_dir)


def _get_redis() -> Any:
    """获取 Redis 客户端。"""
    from framework.commons.redis_client import redis_client

    return redis_client.client


def cmd_list(args: argparse.Namespace) -> None:
    """列出所有已注册的任务。"""
    _init_env()
    from worker.plugin import list_plugins

    plugins = list_plugins()
    if not plugins:
        print("无已注册任务")
        return

    print(f"{'任务名称':<45} {'队列':<10} {'类型':<12} {'描述'}")
    print("-" * 100)
    for name, manifest in sorted(plugins.items()):
        print(
            f"{name:<45} {manifest.queue:<10} {manifest.task_type:<12} "
            f"{manifest.task_name or manifest.description}"
        )


def cmd_run(args: argparse.Namespace) -> None:
    """发送任务到 Celery 队列。"""
    _init_env()

    task_name: str = args.task_name

    # 构建 kwargs
    kwargs: dict[str, Any] = {}

    if args.symbols:
        kwargs["symbols"] = [s.strip() for s in args.symbols.split(",")]

    if args.mode:
        kwargs["mode"] = args.mode

    if args.start_date:
        kwargs["start_date"] = args.start_date

    if args.factor_ids:
        kwargs["factor_ids"] = [f.strip() for f in args.factor_ids.split(",")]

    # 解析额外 kwargs: --kwargs key1=val1 key2=val2
    if args.kwargs:
        for kv in args.kwargs:
            key, _, val = kv.partition("=")
            if not key or not val:
                print(f"无效的 kwargs 格式: {kv}，应为 key=value")
                sys.exit(1)
            # 尝试解析 JSON 值
            try:
                kwargs[key] = json.loads(val)
            except (json.JSONDecodeError, ValueError):
                kwargs[key] = val

    # 获取队列
    from worker.plugin import get_manifest

    manifest = get_manifest(task_name)
    queue = manifest.queue if manifest else "celery"

    # 发送任务
    from worker.celery_app import celery_app

    result = celery_app.send_task(task_name, kwargs=kwargs, queue=queue)
    print(f"任务已发送: {task_name}")
    print(f"  Task ID: {result.id}")
    print(f"  Queue:   {queue}")
    print(f"  Kwargs:  {json.dumps(kwargs, ensure_ascii=False, default=str)}")


def cmd_lock_list(args: argparse.Namespace) -> None:  # noqa: ARG001
    """列出所有任务锁。"""
    r = _get_redis()
    keys = r.keys("task_lock:*")
    if not keys:
        print("无任务锁")
        return

    print(f"{'锁键':<50} {'值(Task ID)':<40} {'TTL(秒)'}")
    print("-" * 100)
    for key in sorted(keys):
        val = r.get(key)
        ttl = r.ttl(key)
        ttl_str = str(ttl) if ttl and ttl > 0 else "无过期"
        print(f"{key:<50} {val or '':<40} {ttl_str}")


def cmd_lock_release(args: argparse.Namespace) -> None:
    """释放指定任务的分布式锁。"""
    task_name: str = args.task_name
    lock_key = f"task_lock:{task_name}"

    r = _get_redis()
    val = r.get(lock_key)
    if val is None:
        print(f"锁不存在: {lock_key}")
        return

    deleted = r.delete(lock_key)
    if deleted:
        print(f"锁已释放: {lock_key} (原值: {val})")
    else:
        print(f"锁释放失败: {lock_key}")


def cmd_lock_release_all(args: argparse.Namespace) -> None:  # noqa: ARG001
    """释放所有任务锁。"""
    r = _get_redis()
    keys = r.keys("task_lock:*")
    if not keys:
        print("无任务锁")
        return

    deleted = r.delete(*keys)
    print(f"已释放 {deleted} 个任务锁")


def build_parser() -> argparse.ArgumentParser:
    """构建命令行解析器。"""
    parser = argparse.ArgumentParser(
        prog="worker.cli",
        description="Worker CLI — 任务发送与锁管理工具",
    )
    subparsers = parser.add_subparsers(dest="command", help="子命令")

    # ── list ──
    sub_list = subparsers.add_parser("list", help="列出所有已注册任务")
    sub_list.set_defaults(func=cmd_list)

    # ── run ──
    sub_run = subparsers.add_parser("run", help="发送任务到 Celery 队列")
    sub_run.add_argument("task_name", help="任务名称，如 factor.compute_daily")
    sub_run.add_argument("--symbols", "-s", help="证券代码列表，逗号分隔，如 000001.SZ,600519.SH")
    sub_run.add_argument("--mode", "-m", help="计算模式: incremental / full")
    sub_run.add_argument("--start-date", help="开始日期 YYYY-MM-DD")
    sub_run.add_argument("--factor-ids", "-f", help="因子ID列表，逗号分隔")
    sub_run.add_argument("--kwargs", "-k", nargs="*", help="额外参数 key=value")
    sub_run.set_defaults(func=cmd_run)

    # ── lock-list ──
    sub_lock_list = subparsers.add_parser("lock-list", help="列出所有任务锁")
    sub_lock_list.set_defaults(func=cmd_lock_list)

    # ── lock-release ──
    sub_lock_release = subparsers.add_parser("lock-release", help="释放指定任务的分布式锁")
    sub_lock_release.add_argument("task_name", help="任务名称，如 factor.compute_daily")
    sub_lock_release.set_defaults(func=cmd_lock_release)

    # ── lock-release-all ──
    sub_lock_release_all = subparsers.add_parser("lock-release-all", help="释放所有任务锁")
    sub_lock_release_all.set_defaults(func=cmd_lock_release_all)

    return parser


def main() -> None:
    """CLI 入口。"""
    parser = build_parser()
    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        sys.exit(1)

    args.func(args)


if __name__ == "__main__":
    main()
