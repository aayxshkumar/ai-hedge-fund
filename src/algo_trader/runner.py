"""Algo Trader runner — the main entry point that orchestrates the full trading loop.

Flow:
  1. Load config and connect to Zerodha
  2. Fetch current portfolio state
  3. Check existing positions for stop-loss / take-profit exits
  4. Run decision engine (hedge fund agents + quant strategies)
  5. Risk-check proposed trades
  6. Execute approved orders via Zerodha MCP
  7. Log results and update memory
"""

from __future__ import annotations

import argparse
import logging
import sys
from datetime import datetime

from dotenv import load_dotenv
from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich import box

from src.algo_trader.config import AlgoTraderConfig
from src.algo_trader.decision_engine import DecisionEngine, TradingSignal
from src.algo_trader.executor import ZerodhaExecutor, Order, OrderSide, OrderType, ExecutionResult
from src.algo_trader.hermes_bridge import log_trade, log_action
from src.algo_trader.risk_engine import RiskEngine
from src.algo_trader.strategy_advisor import generate_session_plan, complete_session, SessionPlan
from src.algo_trader.strategy_tracker import StrategyTracker

load_dotenv()

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(name)s] %(levelname)s: %(message)s")
log = logging.getLogger("algo_trader")
console = Console()


class AlgoTrader:
    """Top-level orchestrator for the AI algo trading system."""

    def __init__(self, config: AlgoTraderConfig):
        self.config = config
        self.executor = ZerodhaExecutor(config)
        self.risk = RiskEngine(config)
        self.engine = DecisionEngine(config)
        self.strategy_tracker = StrategyTracker()
        self.session_plan: SessionPlan | None = None
        self.paper_trader = None  # set externally when in paper mode
        self.tradebook = None     # set externally
        self._execution_log: list[dict] = []
        self._session_trades: list[dict] = []

    def pre_session(self, tradebook=None):
        """Pre-session: generate Hermes session plan and validate strategies."""
        if not self.config.hermes_learning:
            self.session_plan = SessionPlan.default()
            self.engine.set_session_plan(self.session_plan)
            return self.session_plan

        console.print("\n[bold cyan]Pre-Session: Hermes generating strategy plan...[/bold cyan]")
        try:
            self.session_plan = generate_session_plan(
                tradebook=tradebook or self.tradebook,
                model_name=self.config.model_name,
            )
        except Exception as e:
            log.warning("Session plan generation failed: %s", e)
            self.session_plan = SessionPlan.default()

        self.engine.set_session_plan(self.session_plan)

        console.print(f"  Asset allocation: {self.session_plan.asset_allocation}")
        console.print(f"  Active strategies: {len(self.session_plan.strategy_weights)}")
        if self.session_plan.focus_tickers:
            console.print(f"  Focus tickers: {', '.join(self.session_plan.focus_tickers)}")
        if self.session_plan.reasoning:
            console.print(f"  Reasoning: {self.session_plan.reasoning}")

        log_action("SESSION_PLAN", f"Hermes plan: {len(self.session_plan.strategy_weights)} strategies, "
                   f"alloc={self.session_plan.asset_allocation}, focus={self.session_plan.focus_tickers}")

        self._session_trades.clear()
        return self.session_plan

    def post_session(self, tradebook=None):
        """Post-session: analyze results and write Hermes review."""
        if not self._session_trades:
            return

        tb = tradebook or self.tradebook
        stats = {
            "trades": self._session_trades,
            "strategy_weights": self.session_plan.strategy_weights if self.session_plan else {},
        }

        total_pnl = sum(t.get("pnl", 0) or 0 for t in self._session_trades)
        wins = sum(1 for t in self._session_trades if (t.get("pnl", 0) or 0) > 0)
        stats["lessons"] = (
            f"Session: {len(self._session_trades)} trades, "
            f"{wins} wins, P&L ₹{total_pnl:+,.0f}"
        )

        try:
            complete_session(stats)
            console.print(f"\n[bold cyan]Post-Session: {len(self._session_trades)} trades reviewed, "
                         f"P&L ₹{total_pnl:+,.0f}[/bold cyan]")
        except Exception as e:
            log.warning("Post-session review failed: %s", e)

        for t in self._session_trades:
            sname = t.get("strategy_name", "")
            if sname:
                self.strategy_tracker.record_live_trade(
                    sname, t.get("pnl", 0) or 0,
                    t.get("confidence", 0), (t.get("pnl", 0) or 0) > 0,
                )

    def run_cycle(self) -> list[dict]:
        """Execute one full analysis-and-trade cycle. Returns a list of actions taken."""
        console.print(Panel(
            f"[bold cyan]AI Algo Trader — Cycle started at {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} IST[/bold cyan]",
            box=box.DOUBLE,
        ))

        actions = []
        is_paper = self.config.broker.read_only

        # ── 1. Portfolio state ───────────────────────────────────────
        if is_paper and self.paper_trader:
            console.print("\n[bold]1. Fetching paper portfolio state...[/bold]")
            from src.algo_trader.executor import Position
            paper_summary = self.paper_trader.get_summary()
            available_cash = paper_summary.get("cash", 0)
            portfolio_value = paper_summary.get("total_value", 0) or available_cash

            positions = []
            for ticker, pdata in paper_summary.get("positions", {}).items():
                positions.append(Position(
                    ticker=ticker,
                    quantity=pdata.get("quantity", 0),
                    average_price=pdata.get("avg_price", 0),
                    last_price=pdata.get("current_price", 0),
                    pnl=pdata.get("unrealized_pnl", 0),
                    product="CNC",
                ))
            holdings = []

            realized_pnl = paper_summary.get("realized_pnl", 0)
            unrealized_pnl = paper_summary.get("unrealized_pnl", 0)
            self.risk.update_daily_pnl(realized=realized_pnl, unrealized=unrealized_pnl)
            self._print_portfolio_summary(positions, holdings, available_cash, portfolio_value)
        else:
            console.print("\n[bold]1. Fetching portfolio state from Zerodha...[/bold]")
            all_positions = self.executor.get_positions(include_closed=True)
            positions = [p for p in all_positions if p.quantity != 0]
            holdings = self.executor.get_holdings()
            funds = self.executor.get_funds()
            available_cash = funds.get("available_cash", 0)

            portfolio_value = available_cash + sum(abs(p.quantity) * p.last_price for p in positions)
            portfolio_value += sum(h.quantity * h.last_price for h in holdings)

            realized_pnl = sum(p.pnl for p in all_positions if p.quantity == 0)
            unrealized_pnl = sum(p.pnl for p in positions) + sum(h.pnl for h in holdings)
            self.risk.update_daily_pnl(realized=realized_pnl, unrealized=unrealized_pnl)
            self._print_portfolio_summary(positions, holdings, available_cash, portfolio_value)

        # ── 2. Exit checks (stop-loss / take-profit) ────────────────
        console.print("\n[bold]2. Checking existing positions for exits...[/bold]")
        exit_actions = self._check_exits(positions, portfolio_value, available_cash)
        actions.extend(exit_actions)

        # ── 3. Run decision engine (Meta Analyst + 10 quant strategies) ─
        console.print("\n[bold]3. Running AI analysis + quantitative strategies (Meta Analyst → AlgoTrader)...[/bold]")
        signals = self.engine.analyse_universe(self.config.watchlist)
        self._print_signals_table(signals)

        meta_count = sum(1 for s in signals if "meta_analyst" in s.source_signals)
        if meta_count:
            log_action("META_VERDICT_APPLIED", f"{meta_count}/{len(signals)} tickers influenced by 21-agent Meta Analyst verdicts")

        # ── 4. Generate and execute orders ───────────────────────────
        console.print("\n[bold]4. Generating and risk-checking orders...[/bold]")

        equity_signals = [s for s in signals if s.instrument_type == "equity"]
        fno_signals = [s for s in signals if s.instrument_type in ("options", "futures")]

        trade_actions = self._process_signals(equity_signals, positions, portfolio_value, available_cash)
        actions.extend(trade_actions)

        if fno_signals:
            fno_actions = self._process_fno_signals(fno_signals, portfolio_value, available_cash)
            actions.extend(fno_actions)

        mode = "paper" if self.config.broker.read_only else "live"
        for a in actions:
            trade_record = {
                "ticker": a.get("ticker", ""),
                "action": a.get("action", "hold"),
                "quantity": a.get("quantity", 0),
                "price": a.get("price", 0),
                "confidence": a.get("confidence", 0),
                "reasoning": a.get("reasoning", ""),
                "mode": mode,
                "executed": a.get("result").success if a.get("result") else False,
                "instrument_type": a.get("instrument_type", "equity"),
                "strategy_name": a.get("strategy_name", ""),
            }
            log_trade(trade_record)
            self._session_trades.append(trade_record)

        # ── 5. Summary ──────────────────────────────────────────────
        self._print_execution_summary(actions)

        return actions

    def _check_exits(self, positions: list, portfolio_value: float, available_cash: float) -> list[dict]:
        """Scan positions for stop-loss or take-profit triggers."""
        actions = []
        for pos in positions:
            if pos.quantity == 0:
                continue

            should_exit = False
            reason = ""

            if self.risk.should_stop_loss(pos):
                should_exit = True
                reason = "STOP LOSS triggered"
            elif self.risk.should_take_profit(pos):
                should_exit = True
                reason = "TAKE PROFIT triggered"

            if should_exit:
                side = OrderSide.SELL if pos.quantity > 0 else OrderSide.BUY
                order = Order(
                    ticker=pos.ticker,
                    side=side,
                    quantity=abs(pos.quantity),
                    order_type=OrderType.MARKET,
                    product=pos.product,
                )

                result = self._execute_with_risk_check(order, portfolio_value, available_cash, positions, pos.last_price, is_exit=True)
                actions.append({
                    "ticker": pos.ticker,
                    "action": f"EXIT ({reason})",
                    "side": side.value,
                    "quantity": abs(pos.quantity),
                    "result": result,
                })
                console.print(f"  [yellow]{reason}[/yellow] for {pos.ticker}: {side.value} {abs(pos.quantity)} shares")

        return actions

    def _process_signals(
        self,
        signals: list[TradingSignal],
        positions: list,
        portfolio_value: float,
        available_cash: float,
    ) -> list[dict]:
        """Convert trading signals into risk-checked orders."""
        actions = []
        remaining_cash = available_cash
        existing_tickers = {p.ticker for p in positions if p.quantity != 0}

        for signal in signals:
            if signal.action == "hold" or signal.confidence < 0.3:
                continue

            clean_ticker = signal.ticker.replace(".NS", "").replace(".BO", "")

            if signal.action == "buy":
                if clean_ticker in existing_tickers:
                    continue

                prices = self.executor.get_ltp([clean_ticker])
                price = prices.get(clean_ticker, 0)
                if price <= 0:
                    continue

                qty = self.risk.calculate_position_size(
                    clean_ticker, OrderSide.BUY, portfolio_value, price, signal.confidence,
                )
                if qty <= 0:
                    continue

                order = Order(ticker=clean_ticker, side=OrderSide.BUY, quantity=qty)
                result = self._execute_with_risk_check(order, portfolio_value, remaining_cash, positions, price)
                if result.success:
                    remaining_cash -= qty * price
                    existing_tickers.add(clean_ticker)
                actions.append({
                    "ticker": clean_ticker,
                    "action": "BUY",
                    "quantity": qty,
                    "price": price,
                    "confidence": signal.confidence,
                    "reasoning": signal.reasoning,
                    "result": result,
                })

            elif signal.action == "sell":
                matching = [p for p in positions if p.ticker == clean_ticker and p.quantity > 0]
                for pos in matching:
                    order = Order(
                        ticker=clean_ticker,
                        side=OrderSide.SELL,
                        quantity=abs(pos.quantity),
                        product=pos.product,
                    )
                    result = self._execute_with_risk_check(order, portfolio_value, remaining_cash, positions, pos.last_price)
                    if result.success:
                        remaining_cash += abs(pos.quantity) * pos.last_price
                    actions.append({
                        "ticker": clean_ticker,
                        "action": "SELL",
                        "quantity": abs(pos.quantity),
                        "price": pos.last_price,
                        "confidence": signal.confidence,
                        "reasoning": signal.reasoning,
                        "result": result,
                    })

        return actions

    def _execute_with_risk_check(
        self, order: Order, portfolio_value: float, available_cash: float,
        positions: list, price: float, *, is_exit: bool = False,
    ) -> ExecutionResult:
        """Risk-check an order and execute if approved.

        In paper/read-only mode, routes through PaperTrader instead of
        the Zerodha executor so trades actually execute.
        """
        check = self.risk.check_order(order, portfolio_value, available_cash, positions, price, is_exit=is_exit)

        if not check.approved:
            return ExecutionResult(success=False, message=f"Risk rejected: {check.reason}")

        # Paper mode: execute via paper trader
        if self.config.broker.read_only and self.paper_trader:
            try:
                if order.side == OrderSide.BUY:
                    result = self.paper_trader.execute_buy(order.ticker, order.quantity, price)
                else:
                    result = self.paper_trader.execute_sell(order.ticker, order.quantity, price)
                if result.get("success"):
                    return ExecutionResult(
                        success=True,
                        order_id=result.get("order_id", ""),
                        message=result.get("message", "Paper trade executed"),
                    )
                return ExecutionResult(success=False, message=result.get("message", "Paper trade failed"))
            except Exception as e:
                return ExecutionResult(success=False, message=f"Paper trade error: {e}")

        # Live mode
        if self.config.risk.require_confirmation:
            console.print(
                f"  [bold yellow]CONFIRM:[/bold yellow] {order.side.value} {order.quantity} x {order.ticker}"
                f" @ {order.order_type.value} — approve? (auto-approved in auto mode)"
            )

        return self.executor.place_order(order)

    def _process_fno_signals(
        self,
        signals: list[TradingSignal],
        portfolio_value: float,
        available_cash: float,
    ) -> list[dict]:
        """Route F&O signals to paper trader or live executor."""
        actions = []
        fno_exposure = self.paper_trader.margin_used if self.paper_trader else 0

        for signal in signals:
            if signal.action == "hold" or signal.confidence < 0.3:
                continue

            underlying = signal.ticker.replace(".NS", "").replace(".BO", "")

            if signal.instrument_type == "futures" and signal.futures_side:
                lots = signal.futures_lots or 1
                from src.algo_trader.paper_trader import FUTURES_CONFIG
                cfg = FUTURES_CONFIG.get(underlying, {"lot_size": 25, "margin_pct": 0.12})

                check = self.risk.check_fno_order(
                    "futures", underlying, lots, cfg["lot_size"], 0,
                    portfolio_value, available_cash, fno_exposure, cfg["margin_pct"],
                )
                if not check.approved:
                    actions.append({
                        "ticker": underlying, "action": f"FUTURES {signal.futures_side}",
                        "instrument_type": "futures", "strategy_name": signal.strategy_name,
                        "result": ExecutionResult(success=False, message=check.reason),
                    })
                    continue

                if self.paper_trader:
                    result = self.paper_trader.execute_futures_trade(underlying, signal.futures_side, lots)
                    actions.append({
                        "ticker": underlying,
                        "action": f"FUTURES {signal.futures_side.upper()}",
                        "quantity": lots,
                        "price": result.get("fill_price", 0),
                        "confidence": signal.confidence,
                        "reasoning": signal.reasoning,
                        "instrument_type": "futures",
                        "strategy_name": signal.strategy_name,
                        "result": ExecutionResult(success=result.get("success", False),
                                                  message=result.get("message", "")),
                    })
                    if result.get("success"):
                        fno_exposure += result.get("margin_blocked", 0)

            elif signal.instrument_type == "options" and signal.options_legs:
                if self.paper_trader:
                    result = self.paper_trader.execute_options_trade(
                        signal.options_legs, underlying, signal.strategy_name or signal.options_strategy or "",
                    )
                    actions.append({
                        "ticker": underlying,
                        "action": f"OPTIONS {signal.options_strategy or 'MULTI'}",
                        "quantity": len(signal.options_legs),
                        "confidence": signal.confidence,
                        "reasoning": signal.reasoning,
                        "instrument_type": "options",
                        "strategy_name": signal.strategy_name or signal.options_strategy or "",
                        "result": ExecutionResult(success=result.get("success", False),
                                                  message=result.get("message", "")),
                    })

        return actions

    # ── Display helpers ──────────────────────────────────────────────

    def _print_portfolio_summary(self, positions, holdings, cash, total):
        table = Table(title="Portfolio State", box=box.SIMPLE)
        table.add_column("Metric", style="cyan")
        table.add_column("Value", style="green", justify="right")
        table.add_row("Available Cash", f"₹{cash:,.0f}")
        table.add_row("Positions", str(len([p for p in positions if p.quantity != 0])))
        table.add_row("Holdings", str(len(holdings)))
        table.add_row("Total Value", f"₹{total:,.0f}")
        console.print(table)

    def _print_signals_table(self, signals: list[TradingSignal]):
        table = Table(title="Trading Signals", box=box.SIMPLE)
        table.add_column("Ticker", style="cyan")
        table.add_column("Action", style="bold")
        table.add_column("Confidence", justify="right")
        table.add_column("Reasoning")

        for s in signals[:20]:
            color = {"buy": "green", "sell": "red", "hold": "dim"}.get(s.action, "white")
            table.add_row(
                s.ticker,
                f"[{color}]{s.action.upper()}[/{color}]",
                f"{s.confidence:.0%}",
                s.reasoning[:80],
            )
        console.print(table)

    def _print_execution_summary(self, actions: list[dict]):
        if not actions:
            console.print("\n[dim]No trades executed this cycle.[/dim]")
            return

        table = Table(title="Execution Summary", box=box.DOUBLE)
        table.add_column("Ticker", style="cyan")
        table.add_column("Action", style="bold")
        table.add_column("Qty", justify="right")
        table.add_column("Status")

        for a in actions:
            result = a.get("result")
            status = "[green]OK[/green]" if result and result.success else f"[red]{result.message if result else 'N/A'}[/red]"
            table.add_row(a["ticker"], a["action"], str(a.get("quantity", "")), status)
        console.print(table)


def main():
    parser = argparse.ArgumentParser(description="AI Algo Trader — autonomous trading on Indian markets")
    parser.add_argument("--watchlist", type=str, help="Comma-separated tickers (e.g., RELIANCE.NS,TCS.NS,INFY.NS)")
    parser.add_argument("--model", type=str, default="claude-opus-4-6", help="LLM model name")
    parser.add_argument("--provider", type=str, default="Anthropic", help="LLM provider")
    parser.add_argument("--auto-trade", action="store_true", help="Disable confirmation prompts (dangerous!)")
    parser.add_argument("--read-only", action="store_true", default=True, help="Read-only mode (no orders placed)")
    parser.add_argument("--live", action="store_true", help="Enable live trading (disables read-only)")
    parser.add_argument("--max-daily-loss", type=float, default=0.03, help="Max daily loss as fraction (default: 0.03)")
    args = parser.parse_args()

    config = AlgoTraderConfig.from_env()

    if args.watchlist:
        config.watchlist = [t.strip() for t in args.watchlist.split(",")]
    config.model_name = args.model
    config.model_provider = args.provider
    config.risk.require_confirmation = not args.auto_trade
    config.risk.max_daily_loss_pct = args.max_daily_loss

    if args.live:
        config.broker.read_only = False
        console.print("[bold red]LIVE TRADING ENABLED — real orders will be placed![/bold red]")
    else:
        config.broker.read_only = True
        console.print("[bold yellow]READ-ONLY MODE — no orders will be placed.[/bold yellow]")

    trader = AlgoTrader(config)

    console.print(Panel(
        f"[bold]Watchlist:[/bold] {', '.join(config.watchlist)}\n"
        f"[bold]Model:[/bold] {config.model_name} ({config.model_provider})\n"
        f"[bold]Mode:[/bold] {'LIVE' if not config.broker.read_only else 'READ-ONLY'}\n"
        f"[bold]Max daily loss:[/bold] {config.risk.max_daily_loss_pct:.1%}",
        title="AI Algo Trader Configuration",
        box=box.ROUNDED,
    ))

    trader.run_cycle()


if __name__ == "__main__":
    main()
