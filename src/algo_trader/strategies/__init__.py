"""Built-in trading strategies — each produces directional signals with confidence."""

from src.algo_trader.strategies.base import BaseStrategy, StrategySignal  # noqa: F401
from src.algo_trader.strategies.momentum import MomentumStrategy
from src.algo_trader.strategies.mean_reversion import MeanReversionStrategy
from src.algo_trader.strategies.pairs_trading import PairsTradingStrategy
from src.algo_trader.strategies.vwap import VWAPStrategy
from src.algo_trader.strategies.supertrend import SupertrendStrategy
from src.algo_trader.strategies.donchian import DonchianBreakoutStrategy
from src.algo_trader.strategies.ichimoku import IchimokuStrategy
from src.algo_trader.strategies.adx_trend import ADXTrendStrategy
from src.algo_trader.strategies.stoch_rsi import StochRSIStrategy
from src.algo_trader.strategies.obv_divergence import OBVDivergenceStrategy
from src.algo_trader.strategies.ma_ribbon import MARibbonStrategy
from src.algo_trader.strategies.keltner import KeltnerChannelStrategy
from src.algo_trader.strategies.volume_breakout import VolumeBreakoutStrategy
from src.algo_trader.strategies.supertrend_adx import SupertrendADXStrategy
from src.algo_trader.strategies.squeeze_breakout import SqueezeBreakoutStrategy
from src.algo_trader.strategies.vwap_momentum import VWAPMomentumStrategy
from src.algo_trader.strategies.cloud_oscillator import CloudOscillatorStrategy
from src.algo_trader.strategies.volume_trend import VolumeTrendStrategy
from src.algo_trader.strategies.donchian_trailing import DonchianTrailingStrategy
from src.algo_trader.strategies.multi_tf_momentum import MultiTFMomentumStrategy
from src.algo_trader.strategies.candle_pattern_strategy import CandlePatternStrategy
from src.algo_trader.strategies.sentiment_momentum import SentimentMomentumStrategy
from src.algo_trader.strategies.regime_switch import RegimeSwitchStrategy
from src.algo_trader.strategies.opening_range_breakout import OpeningRangeBreakoutStrategy
from src.algo_trader.strategies.gap_fade import GapFadeStrategy
from src.algo_trader.strategies.relative_strength import RelativeStrengthStrategy
from src.algo_trader.strategies.kama_squeeze_momentum import KAMASqueezeStrategy
from src.algo_trader.strategies.smart_money_accumulation import SmartMoneyAccumulationStrategy

STRATEGY_REGISTRY: dict[str, tuple[type, str]] = {
    "momentum": (MomentumStrategy, "EMA/MACD crossover + RSI trend-following"),
    "mean_reversion": (MeanReversionStrategy, "Bollinger Bands + RSI mean reversion"),
    "pairs_trading": (PairsTradingStrategy, "Statistical arbitrage on correlated pairs"),
    "vwap": (VWAPStrategy, "Volume-Weighted Average Price crossover"),
    "supertrend": (SupertrendStrategy, "ATR-based dynamic trend bands"),
    "donchian": (DonchianBreakoutStrategy, "N-day high/low channel breakout (Turtle Traders)"),
    "ichimoku": (IchimokuStrategy, "Ichimoku Cloud trend + momentum confirmation"),
    "adx_trend": (ADXTrendStrategy, "ADX trend strength + DI crossover"),
    "stoch_rsi": (StochRSIStrategy, "Stochastic RSI K/D crossover in extreme zones"),
    "obv_divergence": (OBVDivergenceStrategy, "On-Balance Volume divergence detection"),
    "ma_ribbon": (MARibbonStrategy, "8-EMA ribbon expansion/contraction trend gauge"),
    "keltner": (KeltnerChannelStrategy, "Keltner Channel with Bollinger squeeze detection"),
    "volume_breakout": (VolumeBreakoutStrategy, "Price breakout on high-volume confirmation"),
    "supertrend_adx": (SupertrendADXStrategy, "Supertrend + ADX trend strength fusion"),
    "squeeze_breakout": (SqueezeBreakoutStrategy, "Bollinger-Keltner squeeze + volume breakout"),
    "vwap_momentum": (VWAPMomentumStrategy, "VWAP crossover + MACD histogram momentum"),
    "cloud_oscillator": (CloudOscillatorStrategy, "Ichimoku Cloud + Stochastic RSI timing"),
    "volume_trend": (VolumeTrendStrategy, "OBV divergence + MA Ribbon trend direction"),
    "donchian_trailing": (DonchianTrailingStrategy, "Donchian breakout + ATR trailing stop"),
    "multi_tf_momentum": (MultiTFMomentumStrategy, "EMA ribbon + RSI + volume triple confirmation"),
    "candle_pattern": (CandlePatternStrategy, "Candlestick pattern recognition + volume confirmation"),
    "sentiment_momentum": (SentimentMomentumStrategy, "News sentiment score + RSI momentum blend"),
    "regime_switch": (RegimeSwitchStrategy, "Volatility regime detection — adapts trend-follow vs mean-revert"),
    "opening_range_breakout": (OpeningRangeBreakoutStrategy, "Opening range breakout with ATR normalization"),
    "gap_fade": (GapFadeStrategy, "Overnight gap fade with volume filter"),
    "relative_strength": (RelativeStrengthStrategy, "Cross-sectional momentum — relative strength ranking"),
    "kama_squeeze": (KAMASqueezeStrategy, "KAMA adaptive squeeze momentum — BB/KC squeeze + linreg momentum + volume"),
    "smart_money": (SmartMoneyAccumulationStrategy, "Smart money accumulation — drawdown entry + OBV divergence + volume profile"),
}

__all__ = [
    "BaseStrategy", "StrategySignal",
    "MomentumStrategy", "MeanReversionStrategy", "PairsTradingStrategy",
    "VWAPStrategy", "SupertrendStrategy", "DonchianBreakoutStrategy",
    "IchimokuStrategy", "ADXTrendStrategy", "StochRSIStrategy",
    "OBVDivergenceStrategy", "MARibbonStrategy", "KeltnerChannelStrategy",
    "VolumeBreakoutStrategy", "SupertrendADXStrategy", "SqueezeBreakoutStrategy",
    "VWAPMomentumStrategy", "CloudOscillatorStrategy", "VolumeTrendStrategy",
    "DonchianTrailingStrategy", "MultiTFMomentumStrategy",
    "CandlePatternStrategy", "SentimentMomentumStrategy", "RegimeSwitchStrategy",
    "OpeningRangeBreakoutStrategy", "GapFadeStrategy", "RelativeStrengthStrategy",
    "KAMASqueezeStrategy", "SmartMoneyAccumulationStrategy",
    "STRATEGY_REGISTRY",
]
