from models import Security
import pytest


class TestDatabaseFilter:
    """ORM filter 查询功能测试"""

    @pytest.mark.asyncio(loop_scope="session")
    async def test_security_filter(self, app_with_datasource):
        # 过滤银行行业的证券
        bank_securities = await Security.filter(industry="银行")
        assert len(bank_securities) > 0
        print(f"✅ Filter: 找到 {len(bank_securities)} 家银行")

        # 过滤沪深港通标的
        hs_securities = await Security.filter(is_hs="S")
        assert len(hs_securities) > 0
        print(f"✅ Filter: 找到 {len(hs_securities)} 个沪股通/深股通标的")

        # 过滤并分页
        paginated = await Security.filter(industry="银行", skip=0, limit=1)
        assert len(paginated) == 1
        print(f"✅ Filter with pagination: 返回 {len(paginated)} 条记录")
