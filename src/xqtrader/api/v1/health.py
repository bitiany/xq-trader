from fastapi import APIRouter

router = APIRouter(tags=["健康检查"])


@router.get("/health", summary="健康检查")
async def health_check() -> dict[str, str]:
    return {"status": "ok"}
