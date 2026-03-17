"""Stock search routes — serves NSE + BSE ticker search for the frontend."""

from fastapi import APIRouter, Query
from src.data.nse_stocks import search_nse_stocks, TOTAL_STOCKS, TOTAL_NSE_STOCKS, TOTAL_BSE_STOCKS

router = APIRouter(prefix="/stocks", tags=["stocks"])


@router.get("/search")
async def search_stocks(
    q: str = Query("", description="Search query"),
    limit: int = Query(20, ge=1, le=100),
):
    results = search_nse_stocks(q, limit=limit)
    return {
        "results": results,
        "total_available": TOTAL_STOCKS,
        "nse_count": TOTAL_NSE_STOCKS,
        "bse_count": TOTAL_BSE_STOCKS,
    }
