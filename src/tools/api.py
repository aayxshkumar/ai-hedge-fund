import datetime
import os
import pandas as pd
import yfinance as yf

from src.data.cache import get_cache
from src.data.models import (
    CompanyNews,
    FinancialMetrics,
    Price,
    LineItem,
    InsiderTrade,
)

_cache = get_cache()

# ---------------------------------------------------------------------------
# Ticker resolution – handles Indian stocks (.NS / .BO) automatically
# ---------------------------------------------------------------------------

_resolved_tickers: dict[str, str] = {}
_yf_ticker_objects: dict[str, yf.Ticker] = {}
_YF_CACHE_MAX = 200


def _resolve_ticker(ticker: str) -> str:
    """Resolve a user-provided ticker to a valid yfinance symbol.

    If the ticker already contains a dot (e.g. HDFCBANK.NS), it is used as-is.
    Otherwise we try the bare symbol first (US market), then append .NS (NSE)
    and .BO (BSE) as fallbacks for Indian stocks.
    """
    if ticker in _resolved_tickers:
        return _resolved_tickers[ticker]

    if "." in ticker:
        _resolved_tickers[ticker] = ticker
        return ticker

    for candidate in [ticker, f"{ticker}.NS", f"{ticker}.BO"]:
        try:
            t = yf.Ticker(candidate)
            hist = t.history(period="5d")
            if hist is not None and not hist.empty:
                _resolved_tickers[ticker] = candidate
                return candidate
        except Exception:
            continue

    _resolved_tickers[ticker] = ticker
    return ticker


def _get_yf_ticker(resolved: str) -> yf.Ticker:
    if resolved not in _yf_ticker_objects:
        if len(_yf_ticker_objects) >= _YF_CACHE_MAX:
            oldest = next(iter(_yf_ticker_objects))
            del _yf_ticker_objects[oldest]
        _yf_ticker_objects[resolved] = yf.Ticker(resolved)
    return _yf_ticker_objects[resolved]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _safe_div(a, b):
    if a is None or b is None or b == 0:
        return None
    return a / b


def _safe_sub(a, b):
    if a is None or b is None:
        return None
    return a - b


def _growth_rate(current, previous):
    if current is None or previous is None or previous == 0:
        return None
    return (current - previous) / abs(previous)


def _safe_get_stmt(df, labels, col):
    """Extract a value from a financial-statement DataFrame by trying multiple row labels."""
    if df is None or df.empty or col not in df.columns:
        return None
    for label in (labels if isinstance(labels, list) else [labels]):
        if label in df.index:
            val = df.loc[label, col]
            if pd.notna(val):
                return float(val)
    return None


# ---------------------------------------------------------------------------
# Line-item name mapping  (agent-requested name -> (statement, [yf labels]))
# ---------------------------------------------------------------------------

_LINE_ITEM_MAP: dict[str, tuple[str, list[str]]] = {
    # Income statement
    "revenue": ("financials", ["Total Revenue", "Operating Revenue"]),
    "net_income": ("financials", ["Net Income", "Net Income Common Stockholders"]),
    "operating_income": ("financials", ["Operating Income"]),
    "gross_profit": ("financials", ["Gross Profit"]),
    "ebit": ("financials", ["EBIT"]),
    "ebitda": ("financials", ["EBITDA", "Normalized EBITDA"]),
    "interest_expense": ("financials", ["Interest Expense"]),
    "research_and_development": ("financials", ["Research Development", "Research And Development"]),
    "operating_expense": ("financials", ["Total Operating Expenses", "Operating Expense", "Selling General And Administration"]),
    "earnings_per_share": ("financials", ["Basic EPS", "Diluted EPS"]),
    # Balance sheet
    "total_assets": ("balance_sheet", ["Total Assets"]),
    "total_liabilities": ("balance_sheet", ["Total Liabilities Net Minority Interest"]),
    "current_assets": ("balance_sheet", ["Current Assets"]),
    "current_liabilities": ("balance_sheet", ["Current Liabilities"]),
    "total_debt": ("balance_sheet", ["Total Debt"]),
    "cash_and_equivalents": ("balance_sheet", ["Cash And Cash Equivalents", "Cash Cash Equivalents And Federal Funds Sold", "Cash Financial"]),
    "shareholders_equity": ("balance_sheet", ["Stockholders Equity", "Common Stock Equity"]),
    "outstanding_shares": ("balance_sheet", ["Ordinary Shares Number", "Share Issued"]),
    "goodwill_and_intangible_assets": ("balance_sheet", ["Goodwill And Other Intangible Assets"]),
    # Cash flow
    "free_cash_flow": ("cashflow", ["Free Cash Flow"]),
    "capital_expenditure": ("cashflow", ["Capital Expenditure"]),
    "depreciation_and_amortization": ("cashflow", ["Depreciation And Amortization", "Depreciation Amortization Depletion", "Reconciled Depreciation"]),
    "dividends_and_other_cash_distributions": ("cashflow", ["Cash Dividends Paid", "Common Stock Dividend Paid"]),
    "issuance_or_purchase_of_equity_shares": ("cashflow", ["Net Common Stock Issuance", "Repurchase Of Capital Stock"]),
    "operating_cash_flow": ("cashflow", ["Operating Cash Flow"]),
}


def _get_line_item_value(name: str, stmts: dict[str, pd.DataFrame | None], col, info: dict):
    """Return a single line-item value, supporting both mapped and computed items."""
    if name in _LINE_ITEM_MAP:
        stmt_key, labels = _LINE_ITEM_MAP[name]
        return _safe_get_stmt(stmts.get(stmt_key), labels, col)

    # Computed / derived items
    if name == "gross_margin":
        gp = _safe_get_stmt(stmts.get("financials"), ["Gross Profit"], col)
        rev = _safe_get_stmt(stmts.get("financials"), ["Total Revenue", "Operating Revenue"], col)
        return _safe_div(gp, rev)
    if name == "operating_margin":
        oi = _safe_get_stmt(stmts.get("financials"), ["Operating Income"], col)
        rev = _safe_get_stmt(stmts.get("financials"), ["Total Revenue", "Operating Revenue"], col)
        return _safe_div(oi, rev)
    if name == "debt_to_equity":
        td = _safe_get_stmt(stmts.get("balance_sheet"), ["Total Debt"], col)
        eq = _safe_get_stmt(stmts.get("balance_sheet"), ["Stockholders Equity", "Common Stock Equity"], col)
        return _safe_div(td, eq)
    if name == "working_capital":
        ca = _safe_get_stmt(stmts.get("balance_sheet"), ["Current Assets"], col)
        cl = _safe_get_stmt(stmts.get("balance_sheet"), ["Current Liabilities"], col)
        return _safe_sub(ca, cl)
    if name == "book_value_per_share":
        eq = _safe_get_stmt(stmts.get("balance_sheet"), ["Stockholders Equity", "Common Stock Equity"], col)
        sh = _safe_get_stmt(stmts.get("balance_sheet"), ["Ordinary Shares Number", "Share Issued"], col)
        return _safe_div(eq, sh)
    if name == "return_on_invested_capital":
        ni = _safe_get_stmt(stmts.get("financials"), ["Net Income", "Net Income Common Stockholders"], col)
        eq = _safe_get_stmt(stmts.get("balance_sheet"), ["Stockholders Equity", "Common Stock Equity"], col)
        td = _safe_get_stmt(stmts.get("balance_sheet"), ["Total Debt"], col)
        cash = _safe_get_stmt(stmts.get("balance_sheet"), ["Cash And Cash Equivalents", "Cash Cash Equivalents And Federal Funds Sold", "Cash Financial"], col)
        ic = _safe_sub(((eq or 0) + (td or 0)), cash) if eq is not None or td is not None else None
        return _safe_div(ni, ic)

    return None


def _get_statements(t: yf.Ticker, quarterly: bool = False):
    """Return (financials, balance_sheet, cashflow) DataFrames."""
    if quarterly:
        return t.quarterly_financials, t.quarterly_balance_sheet, t.quarterly_cashflow
    return t.financials, t.balance_sheet, t.cashflow


def _available_periods(stmts: dict[str, pd.DataFrame | None], end_date: str, limit: int):
    """Collect and return sorted period dates from financial statements, filtered by end_date."""
    end_dt = pd.Timestamp(datetime.datetime.strptime(end_date, "%Y-%m-%d"))
    dates: set = set()
    for df in stmts.values():
        if df is not None and not df.empty:
            dates.update(df.columns)
    return sorted([d for d in dates if d <= end_dt], reverse=True)[:limit]


# ===================================================================
# Public API – same signatures as the original financialdatasets.ai
# ===================================================================

def get_prices(ticker: str, start_date: str, end_date: str, api_key: str = None) -> list[Price]:
    """Fetch daily OHLCV price data via Yahoo Finance."""
    cache_key = f"{ticker}_{start_date}_{end_date}"
    if cached_data := _cache.get_prices(cache_key):
        return [Price(**p) for p in cached_data]

    resolved = _resolve_ticker(ticker)
    t = _get_yf_ticker(resolved)

    try:
        end_dt = datetime.datetime.strptime(end_date, "%Y-%m-%d") + datetime.timedelta(days=1)
        hist = t.history(start=start_date, end=end_dt.strftime("%Y-%m-%d"), auto_adjust=True)
    except Exception:
        return []

    if hist is None or hist.empty:
        return []

    prices: list[Price] = []
    for idx, row in hist.iterrows():
        ts = idx.tz_localize(None) if idx.tzinfo else idx
        prices.append(Price(
            open=round(float(row["Open"]), 4),
            close=round(float(row["Close"]), 4),
            high=round(float(row["High"]), 4),
            low=round(float(row["Low"]), 4),
            volume=int(row["Volume"]),
            time=ts.strftime("%Y-%m-%dT00:00:00Z"),
        ))

    if prices:
        _cache.set_prices(cache_key, [p.model_dump() for p in prices])
    return prices


def get_financial_metrics(
    ticker: str,
    end_date: str,
    period: str = "ttm",
    limit: int = 10,
    api_key: str = None,
) -> list[FinancialMetrics]:
    """Build financial metrics from Yahoo Finance data."""
    cache_key = f"{ticker}_{period}_{end_date}_{limit}"
    if cached_data := _cache.get_financial_metrics(cache_key):
        return [FinancialMetrics(**m) for m in cached_data]

    resolved = _resolve_ticker(ticker)
    t = _get_yf_ticker(resolved)
    info = t.info or {}
    currency = info.get("currency", "USD")

    quarterly = period == "quarterly"
    financials, balance_sheet, cashflow = _get_statements(t, quarterly=quarterly)
    stmts = {"financials": financials, "balance_sheet": balance_sheet, "cashflow": cashflow}
    period_label = "quarterly" if quarterly else ("annual" if period == "annual" else "ttm")

    sorted_periods = _available_periods(stmts, end_date, limit)

    metrics_list: list[FinancialMetrics] = []
    for i, col in enumerate(sorted_periods):
        is_latest = i == 0

        # --- raw statement values ---
        rev = _safe_get_stmt(financials, ["Total Revenue", "Operating Revenue"], col)
        ni = _safe_get_stmt(financials, ["Net Income", "Net Income Common Stockholders"], col)
        oi = _safe_get_stmt(financials, ["Operating Income"], col)
        gp = _safe_get_stmt(financials, ["Gross Profit"], col)
        ebit_val = _safe_get_stmt(financials, ["EBIT"], col)
        ebitda_val = _safe_get_stmt(financials, ["EBITDA", "Normalized EBITDA"], col)
        int_exp = _safe_get_stmt(financials, ["Interest Expense"], col)
        eps_val = _safe_get_stmt(financials, ["Basic EPS", "Diluted EPS"], col)

        ta = _safe_get_stmt(balance_sheet, ["Total Assets"], col)
        tl = _safe_get_stmt(balance_sheet, ["Total Liabilities Net Minority Interest"], col)
        ca = _safe_get_stmt(balance_sheet, ["Current Assets"], col)
        cl = _safe_get_stmt(balance_sheet, ["Current Liabilities"], col)
        td = _safe_get_stmt(balance_sheet, ["Total Debt"], col)
        cash_val = _safe_get_stmt(balance_sheet, ["Cash And Cash Equivalents", "Cash Cash Equivalents And Federal Funds Sold", "Cash Financial"], col)
        eq = _safe_get_stmt(balance_sheet, ["Stockholders Equity", "Common Stock Equity"], col)
        shares = _safe_get_stmt(balance_sheet, ["Ordinary Shares Number", "Share Issued"], col)
        inv = _safe_get_stmt(balance_sheet, ["Inventory"], col)
        recv = _safe_get_stmt(balance_sheet, ["Receivables", "Accounts Receivable"], col)

        fcf = _safe_get_stmt(cashflow, ["Free Cash Flow"], col)
        ocf = _safe_get_stmt(cashflow, ["Operating Cash Flow"], col)

        # --- computed ratios ---
        gross_margin = _safe_div(gp, rev)
        operating_margin = _safe_div(oi, rev)
        net_margin = _safe_div(ni, rev)
        roe = _safe_div(ni, eq)
        roa = _safe_div(ni, ta)
        current_ratio = _safe_div(ca, cl)
        quick_ratio = _safe_div(_safe_sub(ca, inv), cl) if ca is not None else None
        cash_ratio = _safe_div(cash_val, cl)
        ocf_ratio = _safe_div(ocf, cl)
        d2e = _safe_div(td, eq)
        d2a = _safe_div(td, ta)
        int_cov = _safe_div(ebit_val or oi, abs(int_exp) if int_exp else None)
        at = _safe_div(rev, ta)
        cogs = _safe_sub(rev, gp)
        inv_turn = _safe_div(cogs, inv)
        recv_turn = _safe_div(rev, recv)
        dso = _safe_div(365.0, recv_turn)
        wc = _safe_sub(ca, cl)
        wc_turn = _safe_div(rev, wc)
        bvps = _safe_div(eq, shares)
        fcf_ps = _safe_div(fcf, shares)
        ic = _safe_sub(((eq or 0) + (td or 0)), cash_val) if eq is not None or td is not None else None
        roic = _safe_div(ni, ic)

        # --- growth rates (compare with next older period) ---
        rev_g = earn_g = eps_g = fcf_g = bv_g = oi_g = ebitda_g = None
        if i + 1 < len(sorted_periods):
            nc = sorted_periods[i + 1]
            rev_g = _growth_rate(rev, _safe_get_stmt(financials, ["Total Revenue", "Operating Revenue"], nc))
            earn_g = _growth_rate(ni, _safe_get_stmt(financials, ["Net Income", "Net Income Common Stockholders"], nc))
            eps_g = _growth_rate(eps_val, _safe_get_stmt(financials, ["Basic EPS", "Diluted EPS"], nc))
            fcf_g = _growth_rate(fcf, _safe_get_stmt(cashflow, ["Free Cash Flow"], nc))
            bv_g = _growth_rate(eq, _safe_get_stmt(balance_sheet, ["Stockholders Equity", "Common Stock Equity"], nc))
            oi_g = _growth_rate(oi, _safe_get_stmt(financials, ["Operating Income"], nc))
            ebitda_g = _growth_rate(ebitda_val, _safe_get_stmt(financials, ["EBITDA", "Normalized EBITDA"], nc))

        # --- market-price-based metrics (latest period only, from .info) ---
        mcap = info.get("marketCap") if is_latest else None
        ev = info.get("enterpriseValue") if is_latest else None
        pe = info.get("trailingPE") if is_latest else None
        pb = info.get("priceToBook") if is_latest else None
        ps = info.get("priceToSalesTrailing12Months") if is_latest else None
        ev_ebitda = info.get("enterpriseToEbitda") if is_latest else None
        ev_rev = info.get("enterpriseToRevenue") if is_latest else None
        peg = info.get("pegRatio") if is_latest else None
        fcf_yield = _safe_div(fcf, mcap)
        payout = info.get("payoutRatio") if is_latest else None

        # Enrich latest period with info where statement data is missing
        if is_latest:
            gross_margin = gross_margin if gross_margin is not None else info.get("grossMargins")
            operating_margin = operating_margin if operating_margin is not None else info.get("operatingMargins")
            net_margin = net_margin if net_margin is not None else info.get("profitMargins")
            roe = roe if roe is not None else info.get("returnOnEquity")
            roa = roa if roa is not None else info.get("returnOnAssets")
            current_ratio = current_ratio if current_ratio is not None else info.get("currentRatio")
            quick_ratio = quick_ratio if quick_ratio is not None else info.get("quickRatio")
            d2e_info = info.get("debtToEquity")
            if d2e is None and d2e_info is not None:
                d2e = d2e_info / 100.0
            rev_g = rev_g if rev_g is not None else info.get("revenueGrowth")
            earn_g = earn_g if earn_g is not None else info.get("earningsGrowth")
            eps_val = eps_val if eps_val is not None else info.get("trailingEps")
            bvps = bvps if bvps is not None else info.get("bookValue")

        period_str = col.strftime("%Y-%m-%d") if hasattr(col, "strftime") else str(col)[:10]

        metrics_list.append(FinancialMetrics(
            ticker=ticker,
            report_period=period_str,
            period=period_label,
            currency=currency,
            market_cap=mcap,
            enterprise_value=ev,
            price_to_earnings_ratio=pe,
            price_to_book_ratio=pb,
            price_to_sales_ratio=ps,
            enterprise_value_to_ebitda_ratio=ev_ebitda,
            enterprise_value_to_revenue_ratio=ev_rev,
            free_cash_flow_yield=fcf_yield,
            peg_ratio=peg,
            gross_margin=gross_margin,
            operating_margin=operating_margin,
            net_margin=net_margin,
            return_on_equity=roe,
            return_on_assets=roa,
            return_on_invested_capital=roic,
            asset_turnover=at,
            inventory_turnover=inv_turn,
            receivables_turnover=recv_turn,
            days_sales_outstanding=dso,
            operating_cycle=None,
            working_capital_turnover=wc_turn,
            current_ratio=current_ratio,
            quick_ratio=quick_ratio,
            cash_ratio=cash_ratio,
            operating_cash_flow_ratio=ocf_ratio,
            debt_to_equity=d2e,
            debt_to_assets=d2a,
            interest_coverage=int_cov,
            revenue_growth=rev_g,
            earnings_growth=earn_g,
            book_value_growth=bv_g,
            earnings_per_share_growth=eps_g,
            free_cash_flow_growth=fcf_g,
            operating_income_growth=oi_g,
            ebitda_growth=ebitda_g,
            payout_ratio=payout,
            earnings_per_share=eps_val,
            book_value_per_share=bvps,
            free_cash_flow_per_share=fcf_ps,
        ))

    # Fallback: build a minimal metric from .info alone when statements are empty
    if not metrics_list and info.get("marketCap"):
        d2e_info = info.get("debtToEquity")
        metrics_list.append(FinancialMetrics(
            ticker=ticker,
            report_period=end_date,
            period=period_label,
            currency=currency,
            market_cap=info.get("marketCap"),
            enterprise_value=info.get("enterpriseValue"),
            price_to_earnings_ratio=info.get("trailingPE"),
            price_to_book_ratio=info.get("priceToBook"),
            price_to_sales_ratio=info.get("priceToSalesTrailing12Months"),
            enterprise_value_to_ebitda_ratio=info.get("enterpriseToEbitda"),
            enterprise_value_to_revenue_ratio=info.get("enterpriseToRevenue"),
            free_cash_flow_yield=None,
            peg_ratio=info.get("pegRatio"),
            gross_margin=info.get("grossMargins"),
            operating_margin=info.get("operatingMargins"),
            net_margin=info.get("profitMargins"),
            return_on_equity=info.get("returnOnEquity"),
            return_on_assets=info.get("returnOnAssets"),
            return_on_invested_capital=None,
            asset_turnover=None, inventory_turnover=None, receivables_turnover=None,
            days_sales_outstanding=None, operating_cycle=None, working_capital_turnover=None,
            current_ratio=info.get("currentRatio"),
            quick_ratio=info.get("quickRatio"),
            cash_ratio=None, operating_cash_flow_ratio=None,
            debt_to_equity=(d2e_info / 100.0) if d2e_info is not None else None,
            debt_to_assets=None, interest_coverage=None,
            revenue_growth=info.get("revenueGrowth"),
            earnings_growth=info.get("earningsGrowth"),
            book_value_growth=None, earnings_per_share_growth=None,
            free_cash_flow_growth=None, operating_income_growth=None, ebitda_growth=None,
            payout_ratio=info.get("payoutRatio"),
            earnings_per_share=info.get("trailingEps"),
            book_value_per_share=info.get("bookValue"),
            free_cash_flow_per_share=None,
        ))

    if metrics_list:
        _cache.set_financial_metrics(cache_key, [m.model_dump() for m in metrics_list])
    return metrics_list


def search_line_items(
    ticker: str,
    line_items: list[str],
    end_date: str,
    period: str = "ttm",
    limit: int = 10,
    api_key: str = None,
) -> list[LineItem]:
    """Search financial-statement line items via Yahoo Finance."""
    resolved = _resolve_ticker(ticker)
    t = _get_yf_ticker(resolved)
    info = t.info or {}
    currency = info.get("currency", "USD")

    quarterly = period == "quarterly"
    financials, balance_sheet, cashflow = _get_statements(t, quarterly=quarterly)
    stmts = {"financials": financials, "balance_sheet": balance_sheet, "cashflow": cashflow}

    sorted_periods = _available_periods(stmts, end_date, limit)

    results: list[LineItem] = []
    for col in sorted_periods:
        item_data: dict = {
            "ticker": ticker,
            "report_period": col.strftime("%Y-%m-%d") if hasattr(col, "strftime") else str(col)[:10],
            "period": "quarterly" if quarterly else "annual",
            "currency": currency,
        }
        for name in line_items:
            item_data[name] = _get_line_item_value(name, stmts, col, info)
        results.append(LineItem(**item_data))

    return results


def get_insider_trades(
    ticker: str,
    end_date: str,
    start_date: str | None = None,
    limit: int = 1000,
    api_key: str = None,
) -> list[InsiderTrade]:
    """Fetch insider transactions from Yahoo Finance."""
    cache_key = f"{ticker}_{start_date or 'none'}_{end_date}_{limit}"
    if cached_data := _cache.get_insider_trades(cache_key):
        return [InsiderTrade(**t) for t in cached_data]

    resolved = _resolve_ticker(ticker)
    t = _get_yf_ticker(resolved)

    try:
        df = t.insider_transactions
    except Exception:
        df = None

    if df is None or df.empty:
        return []

    end_dt = datetime.datetime.strptime(end_date, "%Y-%m-%d")
    start_dt = datetime.datetime.strptime(start_date, "%Y-%m-%d") if start_date else None

    trades: list[InsiderTrade] = []
    for _, row in df.iterrows():
        raw_date = row.get("Start Date")
        if raw_date is None:
            continue
        if isinstance(raw_date, str):
            try:
                txn_dt = datetime.datetime.strptime(raw_date[:10], "%Y-%m-%d")
            except ValueError:
                continue
        else:
            txn_dt = pd.Timestamp(raw_date).to_pydatetime()

        if txn_dt > end_dt:
            continue
        if start_dt and txn_dt < start_dt:
            continue

        shares_val = row.get("Shares")
        value_val = row.get("Value")
        price_per_share = _safe_div(value_val, abs(shares_val)) if shares_val else None
        txn_text = str(row.get("Transaction", "") or "")
        is_sale = "sale" in txn_text.lower()

        trades.append(InsiderTrade(
            ticker=ticker,
            issuer=None,
            name=str(row.get("Insider", "")) or None,
            title=str(row.get("Position", "")) or None,
            is_board_director=None,
            transaction_date=txn_dt.strftime("%Y-%m-%d"),
            transaction_shares=-abs(float(shares_val)) if is_sale and shares_val else (float(shares_val) if shares_val else None),
            transaction_price_per_share=round(float(price_per_share), 2) if price_per_share else None,
            transaction_value=float(value_val) if value_val is not None and pd.notna(value_val) else None,
            shares_owned_before_transaction=None,
            shares_owned_after_transaction=None,
            security_title=None,
            filing_date=txn_dt.strftime("%Y-%m-%d"),
        ))

    trades = trades[:limit]

    if trades:
        _cache.set_insider_trades(cache_key, [t.model_dump() for t in trades])
    return trades


def get_company_news(
    ticker: str,
    end_date: str,
    start_date: str | None = None,
    limit: int = 1000,
    api_key: str = None,
) -> list[CompanyNews]:
    """Fetch company news from Yahoo Finance."""
    cache_key = f"{ticker}_{start_date or 'none'}_{end_date}_{limit}"
    if cached_data := _cache.get_company_news(cache_key):
        return [CompanyNews(**n) for n in cached_data]

    resolved = _resolve_ticker(ticker)
    t = _get_yf_ticker(resolved)

    try:
        raw_news = t.news or []
    except Exception:
        raw_news = []

    end_dt = datetime.datetime.strptime(end_date, "%Y-%m-%d")
    start_dt = datetime.datetime.strptime(start_date, "%Y-%m-%d") if start_date else None

    news_list: list[CompanyNews] = []
    for item in raw_news:
        content = item.get("content", {}) if isinstance(item, dict) else {}
        if not isinstance(content, dict):
            continue

        title = content.get("title", "")
        if not title:
            continue

        pub_date_str = content.get("pubDate", "")
        if pub_date_str:
            try:
                pub_dt = datetime.datetime.fromisoformat(pub_date_str.replace("Z", "+00:00"))
                pub_dt = pub_dt.replace(tzinfo=None)
            except (ValueError, TypeError):
                pub_dt = None
        else:
            pub_dt = None

        if pub_dt:
            if pub_dt > end_dt + datetime.timedelta(days=1):
                continue
            if start_dt and pub_dt < start_dt:
                continue

        provider = content.get("provider", {})
        source = provider.get("displayName", "Yahoo Finance") if isinstance(provider, dict) else "Yahoo Finance"
        canonical = content.get("canonicalUrl", {})
        url = canonical.get("url", "") if isinstance(canonical, dict) else ""

        news_list.append(CompanyNews(
            ticker=ticker,
            title=title,
            author=source,
            source=source,
            date=pub_dt.strftime("%Y-%m-%dT%H:%M:%SZ") if pub_dt else end_date + "T00:00:00Z",
            url=url,
            sentiment=None,
        ))

    news_list = news_list[:limit]

    if news_list:
        _cache.set_company_news(cache_key, [n.model_dump() for n in news_list])
    return news_list


def get_market_cap(
    ticker: str,
    end_date: str,
    api_key: str = None,
) -> float | None:
    """Return point-in-time market cap as of *end_date*.

    First tries FinancialMetrics (period-appropriate).  Falls back to
    an estimate: shares-outstanding × price-on-end_date via yfinance
    history.  Only uses live `info` as a last resort.
    """
    metrics = get_financial_metrics(ticker, end_date, api_key=api_key)
    if metrics and metrics[0].market_cap:
        return metrics[0].market_cap

    resolved = _resolve_ticker(ticker)
    t = _get_yf_ticker(resolved)

    try:
        hist = t.history(start=end_date, period="5d")
        if hist is not None and not hist.empty:
            price_at_date = float(hist["Close"].iloc[0])
            shares = (t.info or {}).get("sharesOutstanding")
            if shares:
                return price_at_date * float(shares)
    except Exception:
        pass

    mcap = (t.info or {}).get("marketCap")
    if mcap:
        return float(mcap)
    return None


def prices_to_df(prices: list[Price]) -> pd.DataFrame:
    """Convert a list of Price objects to a pandas DataFrame."""
    if not prices:
        return pd.DataFrame()
    df = pd.DataFrame([p.model_dump() for p in prices])
    df["Date"] = pd.to_datetime(df["time"])
    df.set_index("Date", inplace=True)
    numeric_cols = ["open", "close", "high", "low", "volume"]
    for col in numeric_cols:
        df[col] = pd.to_numeric(df[col], errors="coerce")
    df.sort_index(inplace=True)
    return df


def get_price_data(ticker: str, start_date: str, end_date: str, api_key: str = None) -> pd.DataFrame:
    """Convenience wrapper: get_prices + prices_to_df."""
    prices = get_prices(ticker, start_date, end_date, api_key=api_key)
    return prices_to_df(prices)
