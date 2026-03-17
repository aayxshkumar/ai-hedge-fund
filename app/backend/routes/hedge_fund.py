import re

from fastapi import APIRouter, HTTPException, Request, Depends
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session
import asyncio

_SAFE_ID = re.compile(r"^[a-zA-Z0-9_\-]+$")

from app.backend.database import get_db
from app.backend.models.schemas import ErrorResponse, HedgeFundRequest, BacktestRequest, BacktestDayResult, BacktestPerformanceMetrics
from app.backend.models.events import StartEvent, ProgressUpdateEvent, ErrorEvent, CompleteEvent
from app.backend.services.graph import create_graph, parse_hedge_fund_response, run_graph_async
from app.backend.services.portfolio import create_portfolio
from app.backend.services.backtest_service import BacktestService
from app.backend.services.api_key_service import ApiKeyService
from src.utils.progress import progress
from src.utils.analysts import get_agents_list

router = APIRouter(prefix="/hedge-fund")

@router.post(
    path="/run",
    responses={
        200: {"description": "Successful response with streaming updates"},
        400: {"model": ErrorResponse, "description": "Invalid request parameters"},
        500: {"model": ErrorResponse, "description": "Internal server error"},
    },
)
async def run(request_data: HedgeFundRequest, request: Request, db: Session = Depends(get_db)):
    try:
        # Hydrate API keys from database if not provided
        if not request_data.api_keys:
            api_key_service = ApiKeyService(db)
            request_data.api_keys = api_key_service.get_api_keys_dict()

        # Create the portfolio
        portfolio = create_portfolio(request_data.initial_cash, request_data.margin_requirement, request_data.tickers, request_data.portfolio_positions)

        # Construct agent graph using the React Flow graph structure
        graph = create_graph(
            graph_nodes=request_data.graph_nodes,
            graph_edges=request_data.graph_edges
        )
        graph = graph.compile()

        # Log a test progress update for debugging
        progress.update_status("system", None, "Preparing hedge fund run")

        # Convert model_provider to string if it's an enum
        model_provider = request_data.model_provider
        if hasattr(model_provider, "value"):
            model_provider = model_provider.value

        # Function to detect client disconnection
        async def wait_for_disconnect():
            """Wait for client disconnect and return True when it happens"""
            try:
                while True:
                    message = await request.receive()
                    if message["type"] == "http.disconnect":
                        return True
            except Exception:
                return True

        # Set up streaming response
        async def event_generator():
            # Queue for progress updates
            progress_queue = asyncio.Queue()
            run_task = None
            disconnect_task = None

            # Simple handler to add updates to the queue
            def progress_handler(agent_name, ticker, status, analysis, timestamp):
                event = ProgressUpdateEvent(agent=agent_name, ticker=ticker, status=status, timestamp=timestamp, analysis=analysis)
                progress_queue.put_nowait(event)

            # Register our handler with the progress tracker
            progress.register_handler(progress_handler)

            try:
                # Start the graph execution in a background task
                run_task = asyncio.create_task(
                    run_graph_async(
                        graph=graph,
                        portfolio=portfolio,
                        tickers=request_data.tickers,
                        start_date=request_data.start_date,
                        end_date=request_data.end_date,
                        model_name=request_data.model_name,
                        model_provider=model_provider,
                        request=request_data,  # Pass the full request for agent-specific model access
                    )
                )
                
                # Start the disconnect detection task
                disconnect_task = asyncio.create_task(wait_for_disconnect())
                
                # Send initial message
                yield StartEvent().to_sse()

                # Stream progress updates until run_task completes or client disconnects
                while not run_task.done():
                    # Check if client disconnected
                    if disconnect_task.done():
                        print("Client disconnected, cancelling hedge fund execution")
                        run_task.cancel()
                        try:
                            await run_task
                        except asyncio.CancelledError:
                            pass
                        return

                    # Either get a progress update or wait a bit
                    try:
                        event = await asyncio.wait_for(progress_queue.get(), timeout=1.0)
                        yield event.to_sse()
                    except asyncio.TimeoutError:
                        # Just continue the loop
                        pass

                # Get the final result
                try:
                    result = await run_task
                except asyncio.CancelledError:
                    print("Task was cancelled")
                    return

                if not result or not result.get("messages"):
                    yield ErrorEvent(message="Failed to generate hedge fund decisions").to_sse()
                    return

                # Send the final result
                complete_payload = {
                    "decisions": parse_hedge_fund_response(result.get("messages", [])[-1].content),
                    "analyst_signals": result.get("data", {}).get("analyst_signals", {}),
                    "current_prices": result.get("data", {}).get("current_prices", {}),
                }
                final_data = CompleteEvent(data=complete_payload)
                yield final_data.to_sse()

                # Auto-save flow run for later review
                try:
                    from pathlib import Path
                    import json as _json
                    from datetime import datetime as _dt
                    hist_dir = Path(__file__).parent.parent.parent.parent / "outputs" / "analysis_history"
                    hist_dir.mkdir(parents=True, exist_ok=True)
                    ts = _dt.now().strftime("%Y%m%d_%H%M%S")
                    tickers_slug = "_".join(t.replace(".NS", "").replace(".BO", "") for t in request_data.tickers[:5])
                    with open(hist_dir / f"{ts}_flow_{tickers_slug}.json", "w") as _f:
                        _json.dump({"timestamp": _dt.now().isoformat(), "source": "flow", "tickers": request_data.tickers, "model": request_data.model_name, "results": complete_payload}, _f, indent=2, default=str)
                except Exception:
                    pass

            except asyncio.CancelledError:
                print("Event generator cancelled")
                return
            finally:
                # Clean up
                progress.unregister_handler(progress_handler)
                if run_task and not run_task.done():
                    run_task.cancel()
                    try:
                        await run_task
                    except asyncio.CancelledError:
                        pass
                if disconnect_task and not disconnect_task.done():
                    disconnect_task.cancel()

        # Return a streaming response
        return StreamingResponse(event_generator(), media_type="text/event-stream")

    except HTTPException as e:
        raise e
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"An error occurred while processing the request: {str(e)}")

@router.post(
    path="/backtest",
    responses={
        200: {"description": "Successful response with streaming backtest updates"},
        400: {"model": ErrorResponse, "description": "Invalid request parameters"},
        500: {"model": ErrorResponse, "description": "Internal server error"},
    },
)
async def backtest(request_data: BacktestRequest, request: Request, db: Session = Depends(get_db)):
    """Run a continuous backtest over a time period with streaming updates."""
    try:
        # Hydrate API keys from database if not provided
        if not request_data.api_keys:
            api_key_service = ApiKeyService(db)
            request_data.api_keys = api_key_service.get_api_keys_dict()

        # Convert model_provider to string if it's an enum
        model_provider = request_data.model_provider
        if hasattr(model_provider, "value"):
            model_provider = model_provider.value

        # Create the portfolio (same as /run endpoint)
        portfolio = create_portfolio(
            request_data.initial_capital, 
            request_data.margin_requirement, 
            request_data.tickers, 
            request_data.portfolio_positions
        )

        # Construct agent graph using the React Flow graph structure (same as /run endpoint)
        graph = create_graph(graph_nodes=request_data.graph_nodes, graph_edges=request_data.graph_edges)
        graph = graph.compile()

        # Create backtest service with the compiled graph
        backtest_service = BacktestService(
            graph=graph,
            portfolio=portfolio,
            tickers=request_data.tickers,
            start_date=request_data.start_date,
            end_date=request_data.end_date,
            initial_capital=request_data.initial_capital,
            model_name=request_data.model_name,
            model_provider=model_provider,
            request=request_data,  # Pass the full request for agent-specific model access
        )

        # Function to detect client disconnection
        async def wait_for_disconnect():
            """Wait for client disconnect and return True when it happens"""
            try:
                while True:
                    message = await request.receive()
                    if message["type"] == "http.disconnect":
                        return True
            except Exception:
                return True

        # Set up streaming response
        async def event_generator():
            progress_queue = asyncio.Queue()
            backtest_task = None
            disconnect_task = None

            # Global progress handler to capture individual agent updates during backtest
            def progress_handler(agent_name, ticker, status, analysis, timestamp):
                event = ProgressUpdateEvent(agent=agent_name, ticker=ticker, status=status, timestamp=timestamp, analysis=analysis)
                progress_queue.put_nowait(event)

            # Progress callback to handle backtest-specific updates
            def progress_callback(update):
                if update["type"] == "progress":
                    event = ProgressUpdateEvent(
                        agent="backtest",
                        ticker=None,
                        status=f"Processing {update['current_date']} ({update['current_step']}/{update['total_dates']})",
                        timestamp=None,
                        analysis=None
                    )
                    progress_queue.put_nowait(event)
                elif update["type"] == "backtest_result":
                    # Convert day result to a streaming event
                    backtest_result = BacktestDayResult(**update["data"])
                    
                    # Send the full day result data as JSON in the analysis field
                    import json
                    analysis_data = json.dumps(update["data"])
                    
                    event = ProgressUpdateEvent(
                        agent="backtest",
                        ticker=None,
                        status=f"Completed {backtest_result.date} - Portfolio: ${backtest_result.portfolio_value:,.2f}",
                        timestamp=None,
                        analysis=analysis_data
                    )
                    progress_queue.put_nowait(event)

            # Register our handler with the progress tracker to capture agent updates
            progress.register_handler(progress_handler)
            
            try:
                # Start the backtest in a background task
                backtest_task = asyncio.create_task(
                    backtest_service.run_backtest_async(progress_callback=progress_callback)
                )
                
                # Start the disconnect detection task
                disconnect_task = asyncio.create_task(wait_for_disconnect())
                
                # Send initial message
                yield StartEvent().to_sse()

                # Stream progress updates until backtest_task completes or client disconnects
                while not backtest_task.done():
                    # Check if client disconnected
                    if disconnect_task.done():
                        print("Client disconnected, cancelling backtest execution")
                        backtest_task.cancel()
                        try:
                            await backtest_task
                        except asyncio.CancelledError:
                            pass
                        return

                    # Either get a progress update or wait a bit
                    try:
                        event = await asyncio.wait_for(progress_queue.get(), timeout=1.0)
                        yield event.to_sse()
                    except asyncio.TimeoutError:
                        # Just continue the loop
                        pass

                # Get the final result
                try:
                    result = await backtest_task
                except asyncio.CancelledError:
                    print("Backtest task was cancelled")
                    return

                if not result:
                    yield ErrorEvent(message="Failed to complete backtest").to_sse()
                    return

                # Send the final result
                performance_metrics = BacktestPerformanceMetrics(**result["performance_metrics"])
                final_data = CompleteEvent(
                    data={
                        "performance_metrics": performance_metrics.model_dump(),
                        "final_portfolio": result["final_portfolio"],
                        "total_days": len(result["results"]),
                    }
                )
                yield final_data.to_sse()

            except asyncio.CancelledError:
                print("Backtest event generator cancelled")
                return
            finally:
                # Clean up
                progress.unregister_handler(progress_handler)
                if backtest_task and not backtest_task.done():
                    backtest_task.cancel()
                    try:
                        await backtest_task
                    except asyncio.CancelledError:
                        pass
                if disconnect_task and not disconnect_task.done():
                    disconnect_task.cancel()

        # Return a streaming response
        return StreamingResponse(event_generator(), media_type="text/event-stream")

    except HTTPException as e:
        raise e
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"An error occurred while processing the backtest request: {str(e)}")


from pydantic import BaseModel as PydanticBaseModel

class AnalyzeRequest(PydanticBaseModel):
    tickers: list[str]
    analysts: list[str] | None = None
    model_name: str = "claude-opus-4-6"

@router.post(
    path="/analyze",
    responses={
        200: {"description": "Simplified stock analysis result"},
        400: {"model": ErrorResponse, "description": "Invalid request parameters"},
        500: {"model": ErrorResponse, "description": "Internal server error"},
    },
)
async def analyze(request_data: AnalyzeRequest, db: Session = Depends(get_db)):
    """Simplified analysis endpoint: give tickers, get decisions. Uses Claude only."""
    from datetime import datetime, timedelta
    from src.main import create_workflow, parse_hedge_fund_response
    from langchain_core.messages import HumanMessage
    from src.utils.analysts import ANALYST_CONFIG

    try:
        api_key_service = ApiKeyService(db)
        api_keys = api_key_service.get_api_keys_dict()

        selected_analysts = request_data.analysts
        if not selected_analysts:
            selected_analysts = list(ANALYST_CONFIG.keys())

        end_date = datetime.now().strftime("%Y-%m-%d")
        start_date = (datetime.now() - timedelta(days=90)).strftime("%Y-%m-%d")

        portfolio = {
            "cash": 1000000,
            "positions": {},
        }

        workflow = create_workflow(selected_analysts)
        agent = workflow.compile()

        loop = asyncio.get_running_loop()
        result = await loop.run_in_executor(None, lambda: agent.invoke({
            "messages": [
                HumanMessage(content="Make trading decisions based on the provided data.")
            ],
            "data": {
                "tickers": request_data.tickers,
                "portfolio": portfolio,
                "start_date": start_date,
                "end_date": end_date,
                "analyst_signals": {},
            },
            "metadata": {
                "show_reasoning": False,
                "model_name": request_data.model_name,
                "model_provider": "Anthropic",
                "request": type("Req", (), {
                    "api_keys": api_keys,
                    "get_agent_model_config": lambda self, agent_id: (request_data.model_name, "Anthropic"),
                })(),
            },
        }))

        decisions = parse_hedge_fund_response(result["messages"][-1].content)
        analyst_signals = result.get("data", {}).get("analyst_signals", {})
        current_prices = result.get("data", {}).get("current_prices", {})

        return {
            "decisions": decisions,
            "analyst_signals": analyst_signals,
            "current_prices": current_prices,
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Analysis failed: {str(e)}")


class DetailedAnalyzeRequest(PydanticBaseModel):
    tickers: list[str]
    analysts: list[str] | None = None
    model_name: str = "claude-opus-4-6"


def _compute_technical(df) -> dict:
    """Compute technical indicators from a price DataFrame."""
    import numpy as np
    close = df["Close"]
    high = df["High"]
    low = df["Low"]

    ema12 = close.ewm(span=12).mean()
    ema26 = close.ewm(span=26).mean()
    macd_line = ema12 - ema26
    signal_line = macd_line.ewm(span=9).mean()
    histogram = macd_line - signal_line

    ema50 = close.ewm(span=50).mean()
    ema200 = close.ewm(span=200).mean()

    delta = close.diff()
    gain = delta.where(delta > 0, 0.0).rolling(14).mean()
    loss = (-delta.where(delta < 0, 0.0)).rolling(14).mean()
    rs = gain / loss.replace(0, np.nan)
    rsi = 100 - (100 / (1 + rs))

    bb_mid = close.rolling(20).mean()
    bb_std = close.rolling(20).std()
    bb_upper = bb_mid + 2 * bb_std
    bb_lower = bb_mid - 2 * bb_std

    recent_high = high.rolling(20).max()
    recent_low = low.rolling(20).min()

    trend = "Bullish" if float(ema50.iloc[-1]) > float(ema200.iloc[-1]) else "Bearish"

    returns = close.pct_change().dropna()
    volatility = float(returns.std() * np.sqrt(252))
    max_dd = float(((close / close.cummax()) - 1).min())

    from src.algo_trader.strategies.candle_patterns import detect_patterns
    candle_result = detect_patterns(df, lookback=5)

    return {
        "rsi": round(float(rsi.iloc[-1]), 1) if not np.isnan(rsi.iloc[-1]) else None,
        "macd": round(float(macd_line.iloc[-1]), 2),
        "macd_signal": round(float(signal_line.iloc[-1]), 2),
        "macd_histogram": round(float(histogram.iloc[-1]), 2),
        "ema_50": round(float(ema50.iloc[-1]), 2),
        "ema_200": round(float(ema200.iloc[-1]), 2),
        "bollinger_upper": round(float(bb_upper.iloc[-1]), 2),
        "bollinger_mid": round(float(bb_mid.iloc[-1]), 2),
        "bollinger_lower": round(float(bb_lower.iloc[-1]), 2),
        "support": round(float(recent_low.iloc[-1]), 2),
        "resistance": round(float(recent_high.iloc[-1]), 2),
        "trend": trend,
        "volatility_annual": round(volatility, 4),
        "max_drawdown_90d": round(max_dd, 4),
        "candle_patterns": candle_result.patterns,
        "candle_bias": candle_result.bias,
        "candle_strength": candle_result.strength,
    }


def _fetch_fundamentals(ticker: str) -> dict:
    """Fetch fundamental data from yfinance."""
    import yfinance as yf
    try:
        info = yf.Ticker(ticker).info
        return {
            "market_cap": info.get("marketCap"),
            "pe_ratio": info.get("trailingPE"),
            "pb_ratio": info.get("priceToBook"),
            "eps": info.get("trailingEps"),
            "dividend_yield": info.get("dividendYield"),
            "fifty_two_week_high": info.get("fiftyTwoWeekHigh"),
            "fifty_two_week_low": info.get("fiftyTwoWeekLow"),
            "sector": info.get("sector"),
            "industry": info.get("industry"),
            "beta": info.get("beta"),
            "avg_volume": info.get("averageVolume"),
            "shares_outstanding": info.get("sharesOutstanding"),
            "book_value": info.get("bookValue"),
            "revenue": info.get("totalRevenue"),
            "profit_margin": info.get("profitMargins"),
            "operating_margin": info.get("operatingMargins"),
            "roe": info.get("returnOnEquity"),
            "debt_to_equity": info.get("debtToEquity"),
            "current_ratio": info.get("currentRatio"),
            "free_cash_flow": info.get("freeCashflow"),
            "short_name": info.get("shortName"),
        }
    except Exception:
        return {}


@router.post("/analyze-detailed")
async def analyze_detailed(request_data: DetailedAnalyzeRequest, db: Session = Depends(get_db)):
    """Enhanced analysis endpoint returning technical, fundamental, and AI analysis."""
    from datetime import datetime, timedelta
    from src.main import create_workflow, parse_hedge_fund_response
    from langchain_core.messages import HumanMessage
    from src.utils.analysts import ANALYST_CONFIG
    import yfinance as yf
    import numpy as np

    try:
        api_key_service = ApiKeyService(db)
        api_keys = api_key_service.get_api_keys_dict()

        selected_analysts = request_data.analysts
        if not selected_analysts:
            selected_analysts = list(ANALYST_CONFIG.keys())

        end_date = datetime.now().strftime("%Y-%m-%d")
        start_date = (datetime.now() - timedelta(days=365)).strftime("%Y-%m-%d")
        start_90 = (datetime.now() - timedelta(days=90)).strftime("%Y-%m-%d")

        loop = asyncio.get_running_loop()

        results = {}
        for ticker in request_data.tickers:
            ticker_data: dict = {"ticker": ticker}

            df = await loop.run_in_executor(
                None, lambda t=ticker: yf.Ticker(t).history(start=start_date, end=end_date)
            )

            if df is not None and not df.empty:
                df.columns = [str(c).strip().capitalize() for c in df.columns]

                ticker_data["technical"] = _compute_technical(df)

                last_90 = df.tail(90)
                ohlcv = []
                for idx, row in last_90.iterrows():
                    ohlcv.append({
                        "date": idx.strftime("%Y-%m-%d"),
                        "open": round(float(row["Open"]), 2),
                        "high": round(float(row["High"]), 2),
                        "low": round(float(row["Low"]), 2),
                        "close": round(float(row["Close"]), 2),
                        "volume": int(row["Volume"]),
                    })
                ticker_data["price_history"] = ohlcv
                ticker_data["current_price"] = round(float(df["Close"].iloc[-1]), 2)
            else:
                ticker_data["technical"] = {}
                ticker_data["price_history"] = []
                ticker_data["current_price"] = None

            ticker_data["fundamentals"] = await loop.run_in_executor(None, _fetch_fundamentals, ticker)

            results[ticker] = ticker_data

        portfolio = {"cash": 1000000, "positions": {}}

        decisions = {}
        analyst_signals = {}
        ai_error = None

        try:
            workflow = create_workflow(selected_analysts)
            agent = workflow.compile()

            ai_result = await loop.run_in_executor(None, lambda: agent.invoke({
                "messages": [HumanMessage(content="Make trading decisions based on the provided data.")],
                "data": {
                    "tickers": request_data.tickers,
                    "portfolio": portfolio,
                    "start_date": start_90,
                    "end_date": end_date,
                    "analyst_signals": {},
                },
                "metadata": {
                    "show_reasoning": True,
                    "model_name": request_data.model_name,
                    "model_provider": "Anthropic",
                    "request": type("Req", (), {
                        "api_keys": api_keys,
                        "get_agent_model_config": lambda self, agent_id: (request_data.model_name, "Anthropic"),
                    })(),
                },
            }))

            decisions = parse_hedge_fund_response(ai_result["messages"][-1].content)
            analyst_signals = ai_result.get("data", {}).get("analyst_signals", {})
        except Exception as ai_err:
            import traceback
            traceback.print_exc()
            ai_error = str(ai_err)

        for ticker in request_data.tickers:
            if ticker in results:
                dec = decisions.get(ticker, decisions.get(ticker.replace(".NS", ""), {})) if isinstance(decisions, dict) else {}
                results[ticker]["decision"] = dec if isinstance(dec, dict) else {"action": str(dec), "confidence": 0, "reasoning": ""}

                ticker_signals = {}
                for agent_name, signals in analyst_signals.items():
                    if isinstance(signals, dict) and ticker in signals:
                        ticker_signals[agent_name] = signals[ticker]
                results[ticker]["analyst_signals"] = ticker_signals if ticker_signals else None

                if ai_error and not ticker_signals:
                    results[ticker]["analyst_signals"] = None
                    if not results[ticker].get("decision", {}).get("reasoning"):
                        results[ticker]["decision"] = {
                            "action": "hold",
                            "confidence": 0,
                            "reasoning": f"AI analysis unavailable ({ai_error[:100]}). Technical and fundamental data shown below.",
                        }

                tech = results[ticker].get("technical", {})
                price = results[ticker].get("current_price")
                if price and tech.get("support") and tech.get("resistance"):
                    action = dec.get("action", "hold") if isinstance(dec, dict) else "hold"
                    if "buy" in str(action).lower():
                        results[ticker]["target_price"] = round(tech["resistance"] * 1.02, 2)
                        results[ticker]["stop_loss"] = round(tech["support"] * 0.98, 2)
                    elif "sell" in str(action).lower():
                        results[ticker]["target_price"] = round(tech["support"] * 0.98, 2)
                        results[ticker]["stop_loss"] = round(tech["resistance"] * 1.02, 2)
                    else:
                        results[ticker]["target_price"] = round(tech["resistance"], 2)
                        results[ticker]["stop_loss"] = round(tech["support"], 2)

                # Extract Target Analyst time_horizon and risk_reward_ratio
                target_sig = (results[ticker].get("analyst_signals") or {}).get("target_analyst_agent", {})
                if isinstance(target_sig, dict) and target_sig.get("time_horizon"):
                    results[ticker]["time_horizon"] = target_sig["time_horizon"]
                    results[ticker]["risk_reward_ratio"] = target_sig.get("risk_reward_ratio", 0)
                    if target_sig.get("target_price"):
                        results[ticker]["target_price"] = target_sig["target_price"]
                    if target_sig.get("stop_loss"):
                        results[ticker]["stop_loss"] = target_sig["stop_loss"]

        # Auto-save analysis for later review
        try:
            from pathlib import Path
            import json as _json
            outputs_dir = Path(__file__).parent.parent.parent.parent / "outputs" / "analysis_history"
            outputs_dir.mkdir(parents=True, exist_ok=True)
            ts = datetime.now().strftime("%Y%m%d_%H%M%S")
            tickers_slug = "_".join(t.replace(".NS", "").replace(".BO", "") for t in request_data.tickers[:5])
            fname = f"{ts}_{tickers_slug}.json"
            with open(outputs_dir / fname, "w") as f:
                _json.dump({"timestamp": datetime.now().isoformat(), "tickers": request_data.tickers, "model": request_data.model_name, "results": results}, f, indent=2, default=str)
        except Exception:
            pass

        return {"results": results, "model_used": request_data.model_name}

    except Exception as e:
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Detailed analysis failed: {str(e)}")


@router.get("/analysis-history")
async def get_analysis_history(limit: int = 20):
    """Return saved analysis history for review."""
    from pathlib import Path
    import json as _json
    outputs_dir = Path(__file__).parent.parent.parent.parent / "outputs" / "analysis_history"
    if not outputs_dir.exists():
        return {"history": []}
    files = sorted(outputs_dir.glob("*.json"), reverse=True)[:limit]
    history = []
    for f in files:
        try:
            with open(f) as fh:
                data = _json.load(fh)
            name = f.stem
            if "_discovery_" in name:
                entry_type = "discovery"
                tickers = data.get("last_batch", [])
                timestamp = data.get("generated_at")
                batch_set = {f"{t}.NS" for t in tickers} | set(tickers)
                strong_buys_count = sum(1 for s in data.get("strong_buys", []) if s.get("ticker", "") in batch_set or s.get("ticker", "").replace(".NS", "") in tickers)
                buys_count = sum(1 for s in data.get("buys", []) if s.get("ticker", "") in batch_set or s.get("ticker", "").replace(".NS", "") in tickers)
            elif "_daily_" in name:
                entry_type = "daily"
                tickers = data.get("tickers", [])
                timestamp = data.get("generated_at") or data.get("timestamp")
                strong_buys_count = len(data.get("strong_buys", []))
                buys_count = data.get("verdict_summary", {}).get("buys", 0)
            elif "_penny_" in name:
                entry_type = "penny"
                analyzed = data.get("all_analyzed", [])
                tickers = [s.get("ticker", "") for s in analyzed[:6]]
                timestamp = data.get("scan_time") or data.get("generated_at") or data.get("timestamp")
                strong_buys_count = len(data.get("strong_buys", []))
                buys_count = len(data.get("buys", []))
            elif "_flow_" in name:
                entry_type = "flow"
                tickers = data.get("tickers", [])
                timestamp = data.get("timestamp")
                strong_buys_count = None
            else:
                entry_type = data.get("type") or "analysis"
                tickers = data.get("tickers", [])
                timestamp = data.get("timestamp") or data.get("generated_at")
                strong_buys_count = None
            entry: dict = {
                "id": f.stem,
                "type": entry_type,
                "timestamp": timestamp,
                "tickers": tickers,
                "model": data.get("model"),
            }
            if strong_buys_count is not None:
                entry["strong_buys_count"] = strong_buys_count
                entry["buys_count"] = buys_count
            history.append(entry)
        except Exception:
            continue
    return {"history": history}


@router.get("/analysis-history/{analysis_id}")
async def get_analysis_detail(analysis_id: str):
    """Return a single saved analysis by ID."""
    if not _SAFE_ID.match(analysis_id):
        raise HTTPException(400, "Invalid analysis ID")
    from pathlib import Path
    import json as _json
    fpath = Path(__file__).parent.parent.parent.parent / "outputs" / "analysis_history" / f"{analysis_id}.json"
    if not fpath.exists():
        raise HTTPException(404, "Analysis not found")
    with open(fpath) as f:
        return _json.load(f)


@router.delete("/analysis-history/{analysis_id}")
async def delete_analysis(analysis_id: str):
    """Delete a saved analysis by ID."""
    if not _SAFE_ID.match(analysis_id):
        raise HTTPException(400, "Invalid analysis ID")
    from pathlib import Path
    fpath = Path(__file__).parent.parent.parent.parent / "outputs" / "analysis_history" / f"{analysis_id}.json"
    if not fpath.exists():
        raise HTTPException(404, "Analysis not found")
    fpath.unlink()
    return {"message": "Analysis deleted", "id": analysis_id}


@router.delete("/analysis-history")
async def delete_all_analyses():
    """Delete all saved analyses."""
    from pathlib import Path
    outputs_dir = Path(__file__).parent.parent.parent.parent / "outputs" / "analysis_history"
    if not outputs_dir.exists():
        return {"message": "No analyses to delete", "deleted": 0}
    count = 0
    for f in outputs_dir.glob("*.json"):
        f.unlink()
        count += 1
    return {"message": f"Deleted {count} analyses", "deleted": count}


@router.get(
    path="/agents",
    responses={
        200: {"description": "List of available agents"},
        500: {"model": ErrorResponse, "description": "Internal server error"},
    },
)
async def get_agents():
    """Get the list of available agents."""
    try:
        return {"agents": get_agents_list()}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to retrieve agents: {str(e)}")

