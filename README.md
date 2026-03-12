# AI Hedge Fund (Yahoo Finance Fork)

An AI-powered hedge fund that uses 18 specialized agents to analyze stocks and generate trading signals. Forked from [virattt/ai-hedge-fund](https://github.com/virattt/ai-hedge-fund) and modified to use **Yahoo Finance** as the data source -- making it completely free to use with **US and Indian stocks**.

## What Changed (vs. Original)

- **Replaced Financial Datasets API with Yahoo Finance (`yfinance`)** -- no paid API key needed for financial data
- **Full Indian stock support** -- automatically resolves NSE (`.NS`) and BSE (`.BO`) tickers
- **Ticker auto-detection** -- pass `HDFCBANK` and it finds `HDFCBANK.NS` automatically
- **Comprehensive financial metrics** -- computes 40+ ratios from Yahoo Finance data (margins, growth rates, valuation multiples, liquidity ratios, etc.)
- **Fixed bugs** -- resolved `UnboundLocalError` in news sentiment agent, `AttributeError` in line item lookups

### Key File Changes

| File | Change |
|------|--------|
| `src/tools/api.py` | Complete rewrite -- all 7 API functions now use `yfinance` |
| `src/agents/news_sentiment.py` | Bug fix for unbound variable |
| `.env.example` | Updated to mark `FINANCIAL_DATASETS_API_KEY` as optional/legacy |
| `pyproject.toml` | Added `yfinance` and `openpyxl` dependencies |

## Agents

The system employs 18 agents working together:

| # | Agent | Style |
|---|-------|-------|
| 1 | Warren Buffett | Wonderful companies at fair prices |
| 2 | Charlie Munger | Quality businesses with durable moats |
| 3 | Ben Graham | Deep value with margin of safety |
| 4 | Peter Lynch | Ten-baggers in everyday businesses |
| 5 | Phil Fisher | Growth via deep scuttlebutt research |
| 6 | Aswath Damodaran | Story + numbers + disciplined valuation |
| 7 | Stanley Druckenmiller | Macro + asymmetric opportunities |
| 8 | Cathie Wood | Disruptive innovation and exponential growth |
| 9 | Bill Ackman | Activist investing, bold concentrated positions |
| 10 | Michael Burry | Contrarian deep value |
| 11 | Mohnish Pabrai | Low-risk doubles (Dhandho) |
| 12 | Rakesh Jhunjhunwala | The Big Bull of India |
| 13 | Valuation Agent | Intrinsic value calculation |
| 14 | Sentiment Agent | Market sentiment analysis |
| 15 | Fundamentals Agent | Financial statement analysis |
| 16 | Technicals Agent | Technical indicator analysis |
| 17 | Risk Manager | Risk metrics and position limits |
| 18 | Portfolio Manager | Final trading decisions |

## Disclaimer

This project is for **educational and research purposes only**.

- Not intended for real trading or investment
- No investment advice or guarantees provided
- Past performance does not indicate future results
- Consult a financial advisor for investment decisions

## Quick Start

### 1. Install

```bash
git clone https://github.com/aayxshkumar/ai-hedge-fund.git
cd ai-hedge-fund
```

Install Poetry (if not already installed):

```bash
curl -sSL https://install.python-poetry.org | python3 -
```

Install dependencies:

```bash
poetry install
```

### 2. Set up API keys

```bash
cp .env.example .env
```

Edit `.env` and add at least one LLM API key:

```bash
ANTHROPIC_API_KEY=your-anthropic-api-key
# or OPENAI_API_KEY, GROQ_API_KEY, DEEPSEEK_API_KEY, etc.
```

No financial data API key is needed -- Yahoo Finance is free.

### 3. Run

**US stocks:**

```bash
poetry run python src/main.py --tickers AAPL,MSFT,NVDA --analysts-all --show-reasoning
```

**Indian stocks (auto-resolves .NS/.BO):**

```bash
poetry run python src/main.py --tickers HDFCBANK,SAIL,KPIT,RELIANCE --analysts-all --show-reasoning
```

**With date range and specific model:**

```bash
poetry run python src/main.py \
  --tickers ICICIBANK.NS,ITC.NS,COALINDIA.NS \
  --analysts-all --model claude-sonnet-4-5-20250929 \
  --start-date 2025-12-10 --end-date 2026-03-10 --show-reasoning
```

### Run the Backtester

```bash
poetry run python src/backtester.py --ticker AAPL,MSFT,NVDA
```

## Supported Tickers

| Market | Format | Examples |
|--------|--------|----------|
| US | Bare symbol | `AAPL`, `MSFT`, `NVDA` |
| India (NSE) | `.NS` suffix or bare | `HDFCBANK.NS` or `HDFCBANK` |
| India (BSE) | `.BO` suffix | `HDFCBANK.BO` |

The system auto-detects Indian tickers: if a bare symbol doesn't resolve as a US stock, it tries `.NS` then `.BO` fallback.

## License

This project is licensed under the MIT License - see the LICENSE file for details.

## Credits

Based on [virattt/ai-hedge-fund](https://github.com/virattt/ai-hedge-fund). Yahoo Finance integration and Indian market support added by [@aayxshkumar](https://github.com/aayxshkumar).
