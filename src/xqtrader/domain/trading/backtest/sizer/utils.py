"""仓位工具函数"""


def round_to_lot(size: float, lot_size: int = 100) -> int:
    """按手数向下取整

    Args:
        size: 原始股数
        lot_size: 每手股数，A 股默认 100

    Returns:
        取整后的股数
    """
    return int(size / lot_size) * lot_size
