from xqtrader.domain.security.models import Security


class SecurityService:

    async def list_securities(
        self,
        page: int = 1,
        page_size: int = 20,
        industry: str | None = None,
    ) -> dict:
        skip = (page - 1) * page_size
        filters: dict = {}
        if industry:
            filters["industry"] = industry

        items = await Security.filter(
            skip=skip,
            limit=page_size,
            **filters,
        )
        total = await Security.count(**filters)
        return {
            "items": [item.to_dict() for item in items],
            "total": total,
            "page": page,
            "page_size": page_size,
        }

    async def get_by_symbol(self, symbol: str) -> dict | None:
        security = await Security.get_one_or_none(symbol=symbol)
        if security is None:
            return None
        return security.to_dict()
