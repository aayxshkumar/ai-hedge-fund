"""Centralised configuration for the algo trader."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from dotenv import load_dotenv

load_dotenv()


@dataclass
class BrokerConfig:
    """Zerodha Kite Connect API settings."""

    api_key: str = ""
    api_secret: str = ""
    access_token: str = ""
    read_only: bool = False


@dataclass
class RiskConfig:
    """Risk management guardrails."""

    max_position_pct: float = 0.10        # max 10 % of portfolio per stock
    max_portfolio_exposure: float = 0.80   # max 80 % of capital deployed
    max_single_order_value: float = 100_000  # ₹1 lakh per order
    max_daily_loss_pct: float = 0.03       # stop trading after 3 % daily drawdown
    max_open_positions: int = 15
    stop_loss_pct: float = 0.05            # 5 % trailing stop
    take_profit_pct: float = 0.15          # 15 % take profit
    require_confirmation: bool = True      # human-in-the-loop approval

    # F&O risk
    max_fno_exposure_pct: float = 0.50     # max 50 % of capital in F&O
    max_lots_per_underlying: int = 4
    max_premium_risk_per_trade: float = 25_000
    futures_stop_loss_pct: float = 0.03
    options_max_loss_per_trade: float = 15_000


@dataclass
class StrategyConfig:
    """Parameters for built-in strategies."""

    # Momentum
    momentum_fast_ema: int = 12
    momentum_slow_ema: int = 26
    momentum_signal_ema: int = 9
    momentum_rsi_period: int = 14
    momentum_rsi_overbought: float = 70
    momentum_rsi_oversold: float = 30

    # Mean reversion
    mean_rev_bb_period: int = 20
    mean_rev_bb_std: float = 2.0
    mean_rev_rsi_period: int = 14

    # Pairs trading
    pairs_lookback_days: int = 90
    pairs_zscore_entry: float = 2.0
    pairs_zscore_exit: float = 0.5
    pairs_min_correlation: float = 0.80


@dataclass
class SchedulerConfig:
    """Trading loop timing."""

    market_open: str = "09:15"   # IST
    market_close: str = "15:30"  # IST
    analysis_interval_minutes: int = 5     # fast cycle for responsive trading
    pre_market_analysis_minutes: int = 15  # run analysis 15 min before open


@dataclass
class AlgoTraderConfig:
    """Top-level configuration container."""

    broker: BrokerConfig = field(default_factory=BrokerConfig)
    risk: RiskConfig = field(default_factory=RiskConfig)
    strategy: StrategyConfig = field(default_factory=StrategyConfig)
    scheduler: SchedulerConfig = field(default_factory=SchedulerConfig)

    # Hedge fund integration
    model_name: str = "claude-opus-4-6"
    model_provider: str = "Anthropic"
    use_all_analysts: bool = True
    selected_analysts: list[str] = field(default_factory=list)

    # OpenViking memory
    openviking_enabled: bool = False
    openviking_url: str = "http://localhost:1933"

    # Autonomous trading features
    enable_fno: bool = True
    paper_capital: float = 10_00_000        # ₹10 lakh default paper capital
    prefer_technical: bool = True           # weight technical > fundamental
    hermes_learning: bool = True            # enable Hermes learning loop
    allow_long_term: bool = True            # no restriction on holding period
    fno_bias: float = 0.6                   # 60 % allocation toward F&O vs equity

    # Watchlist
    watchlist: list[str] = field(default_factory=lambda: [
        "RELIANCE.NS", "TCS.NS", "HDFCBANK.NS", "INFY.NS", "ICICIBANK.NS",
        "HINDUNILVR.NS", "ITC.NS", "SBIN.NS", "BHARTIARTL.NS", "KOTAKBANK.NS",
        "LT.NS", "AXISBANK.NS", "ASIANPAINT.NS", "MARUTI.NS", "TITAN.NS",
    ])

    @classmethod
    def from_env(cls) -> AlgoTraderConfig:
        """Build config from environment variables with sensible defaults."""
        cfg = cls()
        cfg.model_name = os.getenv("ALGO_MODEL_NAME", cfg.model_name)
        cfg.model_provider = os.getenv("ALGO_MODEL_PROVIDER", cfg.model_provider)

        if os.getenv("ALGO_WATCHLIST"):
            cfg.watchlist = [t.strip() for t in os.getenv("ALGO_WATCHLIST").split(",")]

        cfg.risk.max_daily_loss_pct = float(os.getenv("ALGO_MAX_DAILY_LOSS", cfg.risk.max_daily_loss_pct))
        cfg.risk.require_confirmation = os.getenv("ALGO_AUTO_TRADE", "").lower() != "true"
        cfg.broker.read_only = os.getenv("ALGO_READ_ONLY", "true").lower() == "true"
        cfg.broker.api_key = os.getenv("KITE_API_KEY", "")
        cfg.broker.api_secret = os.getenv("KITE_API_SECRET", "")
        cfg.broker.access_token = os.getenv("KITE_ACCESS_TOKEN", "")
        cfg.scheduler.analysis_interval_minutes = int(os.getenv("ALGO_INTERVAL_MINUTES", str(cfg.scheduler.analysis_interval_minutes)))
        cfg.openviking_enabled = os.getenv("OPENVIKING_ENABLED", "").lower() == "true"

        return cfg
