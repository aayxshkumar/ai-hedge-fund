"""Trading scheduler — runs the algo trader in a loop during market hours.

Handles:
- Pre-market analysis (run before 9:15 IST)
- Periodic intraday analysis (every N minutes during market hours)
- End-of-day portfolio review
- Holiday/weekend detection
"""

from __future__ import annotations

import logging
import time
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from rich.console import Console

from src.algo_trader.config import AlgoTraderConfig
from src.algo_trader.runner import AlgoTrader

log = logging.getLogger(__name__)
console = Console()

IST = ZoneInfo("Asia/Kolkata")

# NSE holidays 2025–2026 (update annually)
MARKET_HOLIDAYS = {
    "2025-01-26", "2025-02-26", "2025-03-14", "2025-03-31", "2025-04-10",
    "2025-04-14", "2025-04-18", "2025-05-01", "2025-06-27", "2025-08-15",
    "2025-08-27", "2025-10-02", "2025-10-20", "2025-10-21", "2025-11-05",
    "2025-11-26", "2025-12-25",
    "2026-01-26", "2026-03-10", "2026-03-30", "2026-04-03", "2026-04-14",
    "2026-05-01", "2026-06-17", "2026-07-17", "2026-08-15", "2026-10-02",
    "2026-10-19", "2026-10-21", "2026-11-09", "2026-11-26", "2026-12-25",
}


def _now_ist() -> datetime:
    """Get current time in IST."""
    return datetime.now(IST)


def _is_market_day(dt: datetime) -> bool:
    if dt.weekday() >= 5:
        return False
    return dt.strftime("%Y-%m-%d") not in MARKET_HOLIDAYS


def _parse_time(time_str: str) -> tuple[int, int]:
    parts = time_str.split(":")
    return int(parts[0]), int(parts[1])


class TradingScheduler:
    """Runs the algo trader on a schedule aligned with Indian market hours."""

    def __init__(self, config: AlgoTraderConfig):
        self.config = config
        self.trader = AlgoTrader(config)
        open_h, open_m = _parse_time(config.scheduler.market_open)
        close_h, close_m = _parse_time(config.scheduler.market_close)
        self.market_open_minutes = open_h * 60 + open_m
        self.market_close_minutes = close_h * 60 + close_m

    def run_loop(self):
        """Main loop — runs until interrupted."""
        console.print("[bold cyan]Trading scheduler started. Press Ctrl+C to stop.[/bold cyan]")

        while True:
            try:
                now = _now_ist()
                current_minutes = now.hour * 60 + now.minute

                if not _is_market_day(now):
                    console.print(f"[dim]{now.strftime('%Y-%m-%d')} is not a trading day. Sleeping until tomorrow...[/dim]")
                    self._sleep_until_tomorrow()
                    continue

                pre_market_start = self.market_open_minutes - self.config.scheduler.pre_market_analysis_minutes

                if current_minutes < pre_market_start:
                    wait = pre_market_start - current_minutes
                    console.print(f"[dim]Market opens at {self.config.scheduler.market_open} IST. Waiting {wait} min...[/dim]")
                    time.sleep(wait * 60)
                    continue

                if pre_market_start <= current_minutes < self.market_open_minutes:
                    console.print("[yellow]Pre-market analysis window...[/yellow]")
                    self.trader.run_cycle()
                    wait_until_open = self.market_open_minutes - current_minutes
                    time.sleep(max(wait_until_open * 60, 60))
                    continue

                if self.market_open_minutes <= current_minutes < self.market_close_minutes:
                    console.print(f"[green]Market open — running cycle at {now.strftime('%H:%M')} IST[/green]")
                    self.trader.run_cycle()
                    time.sleep(self.config.scheduler.analysis_interval_minutes * 60)
                    continue

                # After market close — run end-of-day review then sleep
                if current_minutes >= self.market_close_minutes:
                    console.print("[yellow]Market closed. Running end-of-day review...[/yellow]")
                    self.trader.run_cycle()
                    self._sleep_until_tomorrow()
                    continue

            except KeyboardInterrupt:
                console.print("\n[bold red]Scheduler stopped by user.[/bold red]")
                break
            except Exception as e:
                log.error("Scheduler error: %s", e, exc_info=True)
                console.print(f"[red]Error: {e}. Retrying in 5 minutes...[/red]")
                time.sleep(300)

    def run_once(self):
        """Run a single cycle immediately regardless of market hours."""
        console.print("[bold]Running single analysis cycle...[/bold]")
        return self.trader.run_cycle()

    def _sleep_until_tomorrow(self):
        now = _now_ist()
        tomorrow = (now + timedelta(days=1)).replace(hour=9, minute=0, second=0, microsecond=0)
        sleep_seconds = (tomorrow - now).total_seconds()
        console.print(f"[dim]Sleeping {sleep_seconds / 3600:.1f} hours until tomorrow 09:00 IST...[/dim]")
        time.sleep(max(sleep_seconds, 60))
