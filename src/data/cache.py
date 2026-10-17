import json
import os
import re
import time
from pathlib import Path

# Statements change quarterly; prices daily. Persisting the cache on disk means
# a restarted server (or a second review the same day) does not re-hit Yahoo,
# which rate-limits hard enough to starve a 49-stock review.
CACHE_DIR = Path(os.getenv("DATA_CACHE_DIR", Path(__file__).resolve().parents[2] / "outputs" / "data_cache"))
TTL_SECONDS = {"prices": 6 * 3600, "financial_metrics": 24 * 3600, "line_items": 24 * 3600,
               "insider_trades": 24 * 3600, "company_news": 6 * 3600}


def _safe_name(key: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.\-]+", "_", key)[:150]


class Cache:
    """In-memory cache for API responses, mirrored to disk with a TTL."""

    def __init__(self):
        self._prices_cache: dict[str, list[dict[str, any]]] = {}
        self._financial_metrics_cache: dict[str, list[dict[str, any]]] = {}
        self._line_items_cache: dict[str, list[dict[str, any]]] = {}
        self._insider_trades_cache: dict[str, list[dict[str, any]]] = {}
        self._company_news_cache: dict[str, list[dict[str, any]]] = {}
        self._disk_ok = True
        try:
            CACHE_DIR.mkdir(parents=True, exist_ok=True)
        except Exception:
            self._disk_ok = False

    def _disk_get(self, kind: str, key: str):
        if not self._disk_ok:
            return None
        path = CACHE_DIR / kind / f"{_safe_name(key)}.json"
        try:
            if path.exists() and time.time() - path.stat().st_mtime < TTL_SECONDS.get(kind, 3600):
                return json.loads(path.read_text())
        except Exception:
            return None
        return None

    def _disk_set(self, kind: str, key: str, data):
        if not self._disk_ok:
            return
        try:
            d = CACHE_DIR / kind
            d.mkdir(parents=True, exist_ok=True)
            tmp = d / f"{_safe_name(key)}.tmp"
            tmp.write_text(json.dumps(data, default=str))
            os.replace(tmp, d / f"{_safe_name(key)}.json")
        except Exception:
            pass

    def _merge_data(self, existing: list[dict] | None, new_data: list[dict], key_field: str) -> list[dict]:
        """Merge existing and new data, avoiding duplicates based on a key field."""
        if not existing:
            return new_data

        # Create a set of existing keys for O(1) lookup
        existing_keys = {item[key_field] for item in existing}

        # Only add items that don't exist yet
        merged = existing.copy()
        merged.extend([item for item in new_data if item[key_field] not in existing_keys])
        return merged

    def get_prices(self, ticker: str) -> list[dict[str, any]] | None:
        """Get cached price data if available."""
        if ticker not in self._prices_cache:
            disk = self._disk_get("prices", ticker)
            if disk is not None:
                self._prices_cache[ticker] = disk
        return self._prices_cache.get(ticker)

    def set_prices(self, ticker: str, data: list[dict[str, any]]):
        """Append new price data to cache."""
        self._prices_cache[ticker] = self._merge_data(self._prices_cache.get(ticker), data, key_field="time")
        self._disk_set("prices", ticker, self._prices_cache[ticker])

    def get_financial_metrics(self, ticker: str) -> list[dict[str, any]]:
        """Get cached financial metrics if available."""
        if ticker not in self._financial_metrics_cache:
            disk = self._disk_get("financial_metrics", ticker)
            if disk is not None:
                self._financial_metrics_cache[ticker] = disk
        return self._financial_metrics_cache.get(ticker)

    def set_financial_metrics(self, ticker: str, data: list[dict[str, any]]):
        """Append new financial metrics to cache."""
        self._financial_metrics_cache[ticker] = self._merge_data(self._financial_metrics_cache.get(ticker), data, key_field="report_period")
        self._disk_set("financial_metrics", ticker, self._financial_metrics_cache[ticker])

    def get_line_items(self, ticker: str) -> list[dict[str, any]] | None:
        """Get cached line items if available."""
        if ticker not in self._line_items_cache:
            disk = self._disk_get("line_items", ticker)
            if disk is not None:
                self._line_items_cache[ticker] = disk
        return self._line_items_cache.get(ticker)

    def set_line_items(self, ticker: str, data: list[dict[str, any]]):
        """Append new line items to cache."""
        self._line_items_cache[ticker] = self._merge_data(self._line_items_cache.get(ticker), data, key_field="report_period")
        self._disk_set("line_items", ticker, self._line_items_cache[ticker])

    def get_insider_trades(self, ticker: str) -> list[dict[str, any]] | None:
        """Get cached insider trades if available."""
        if ticker not in self._insider_trades_cache:
            disk = self._disk_get("insider_trades", ticker)
            if disk is not None:
                self._insider_trades_cache[ticker] = disk
        return self._insider_trades_cache.get(ticker)

    def set_insider_trades(self, ticker: str, data: list[dict[str, any]]):
        """Append new insider trades to cache."""
        self._insider_trades_cache[ticker] = self._merge_data(self._insider_trades_cache.get(ticker), data, key_field="filing_date")  # Could also use transaction_date if preferred
        self._disk_set("insider_trades", ticker, self._insider_trades_cache[ticker])

    def get_company_news(self, ticker: str) -> list[dict[str, any]] | None:
        """Get cached company news if available."""
        if ticker not in self._company_news_cache:
            disk = self._disk_get("company_news", ticker)
            if disk is not None:
                self._company_news_cache[ticker] = disk
        return self._company_news_cache.get(ticker)

    def set_company_news(self, ticker: str, data: list[dict[str, any]]):
        """Append new company news to cache."""
        self._company_news_cache[ticker] = self._merge_data(self._company_news_cache.get(ticker), data, key_field="date")
        self._disk_set("company_news", ticker, self._company_news_cache[ticker])


# Global cache instance
_cache = Cache()


def get_cache() -> Cache:
    """Get the global cache instance."""
    return _cache
