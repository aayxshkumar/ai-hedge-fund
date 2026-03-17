"""Options trading strategies for Bank Nifty and Nifty 50 indices.

Each strategy receives the current option chain and underlying price data,
and returns a list of legs to open or a signal to close.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass

import numpy as np
import pandas as pd

from src.algo_trader.options.chain import OptionChain, OptionContract
from src.algo_trader.options.portfolio import OptionLeg


@dataclass
class OptionsSignal:
    action: str  # "open", "close", "hold"
    legs: list[OptionLeg]
    confidence: float
    reason: str


class BaseOptionsStrategy(ABC):
    name: str = ""
    description: str = ""

    @abstractmethod
    def analyse(
        self,
        chain: OptionChain,
        price_history: pd.DataFrame,
        has_position: bool,
    ) -> OptionsSignal:
        ...

    def _hold(self, reason: str = "") -> OptionsSignal:
        return OptionsSignal(action="hold", legs=[], confidence=0.0, reason=reason)


class LongStraddleStrategy(BaseOptionsStrategy):
    """Buy ATM Call + ATM Put. Profits from large moves in either direction.
    Best before high-volatility events (budget, RBI policy, earnings).
    """
    name = "long_straddle"
    description = "Buy ATM CE + PE — profits from big moves either direction"

    def analyse(self, chain: OptionChain, price_history: pd.DataFrame, has_position: bool) -> OptionsSignal:
        if has_position:
            return self._hold("Position already open")

        closes = price_history["close"].values
        if len(closes) < 20:
            return self._hold("Insufficient data")

        recent_vol = float(np.std(np.diff(np.log(closes[-20:]))) * np.sqrt(252))
        long_vol = float(np.std(np.diff(np.log(closes[-60:]))) * np.sqrt(252)) if len(closes) >= 60 else recent_vol

        # Enter when recent volatility is contracting (expecting expansion)
        if recent_vol > long_vol * 0.9:
            return self._hold("Volatility not contracted enough")

        atm = chain.get_atm_strike()
        call = chain.get_strike(atm, "call")
        put = chain.get_strike(atm, "put")

        if not call or not put:
            return self._hold("ATM strikes not found")

        confidence = min(0.9, 0.5 + (long_vol - recent_vol) / long_vol)
        lots = 1

        legs = [
            OptionLeg(strike=atm, option_type="call", side="long", lots=lots, lot_size=call.lot_size, entry_premium=call.premium),
            OptionLeg(strike=atm, option_type="put", side="long", lots=lots, lot_size=put.lot_size, entry_premium=put.premium),
        ]
        return OptionsSignal(action="open", legs=legs, confidence=confidence, reason=f"Vol contraction {recent_vol:.1%} vs {long_vol:.1%}")


class ShortStraddleStrategy(BaseOptionsStrategy):
    """Sell ATM Call + ATM Put. Profits from low volatility / sideways markets.
    Capped profit, unlimited risk — requires strict stop loss.
    """
    name = "short_straddle"
    description = "Sell ATM CE + PE — profits from sideways/low-volatility markets"

    def analyse(self, chain: OptionChain, price_history: pd.DataFrame, has_position: bool) -> OptionsSignal:
        if has_position:
            return self._hold("Position already open")

        closes = price_history["close"].values
        if len(closes) < 20:
            return self._hold("Insufficient data")

        recent_vol = float(np.std(np.diff(np.log(closes[-20:]))) * np.sqrt(252))
        long_vol = float(np.std(np.diff(np.log(closes[-60:]))) * np.sqrt(252)) if len(closes) >= 60 else recent_vol

        # Enter when recent vol is elevated relative to history (IV > HV)
        if recent_vol < long_vol * 1.1:
            return self._hold("IV not elevated enough")

        atm = chain.get_atm_strike()
        call = chain.get_strike(atm, "call")
        put = chain.get_strike(atm, "put")

        if not call or not put:
            return self._hold("ATM strikes not found")

        confidence = min(0.8, 0.4 + (recent_vol - long_vol) / long_vol)

        legs = [
            OptionLeg(strike=atm, option_type="call", side="short", lots=1, lot_size=call.lot_size, entry_premium=call.premium),
            OptionLeg(strike=atm, option_type="put", side="short", lots=1, lot_size=put.lot_size, entry_premium=put.premium),
        ]
        return OptionsSignal(action="open", legs=legs, confidence=confidence, reason=f"Elevated IV {recent_vol:.1%}")


class LongStrangleStrategy(BaseOptionsStrategy):
    """Buy OTM Call + OTM Put. Cheaper than straddle, needs bigger move to profit."""
    name = "long_strangle"
    description = "Buy OTM CE + PE — cheaper than straddle, needs bigger move"

    def analyse(self, chain: OptionChain, price_history: pd.DataFrame, has_position: bool) -> OptionsSignal:
        if has_position:
            return self._hold("Position already open")

        closes = price_history["close"].values
        if len(closes) < 20:
            return self._hold("Insufficient data")

        recent_vol = float(np.std(np.diff(np.log(closes[-20:]))) * np.sqrt(252))
        long_vol = float(np.std(np.diff(np.log(closes[-60:]))) * np.sqrt(252)) if len(closes) >= 60 else recent_vol

        if recent_vol > long_vol * 0.85:
            return self._hold("Volatility not compressed enough")

        atm = chain.get_atm_strike()
        cfg = {"NIFTY": 50, "BANKNIFTY": 100}.get(chain.underlying, 50)
        otm_distance = cfg * 3

        call_strike = atm + otm_distance
        put_strike = atm - otm_distance
        call = chain.get_strike(call_strike, "call")
        put = chain.get_strike(put_strike, "put")

        if not call or not put:
            return self._hold("OTM strikes not found")

        confidence = min(0.85, 0.45 + (long_vol - recent_vol) / long_vol)

        legs = [
            OptionLeg(strike=call_strike, option_type="call", side="long", lots=1, lot_size=call.lot_size, entry_premium=call.premium),
            OptionLeg(strike=put_strike, option_type="put", side="long", lots=1, lot_size=put.lot_size, entry_premium=put.premium),
        ]
        return OptionsSignal(action="open", legs=legs, confidence=confidence, reason=f"Vol squeeze {recent_vol:.1%}")


class IronCondorStrategy(BaseOptionsStrategy):
    """Sell OTM Call + Put, buy further OTM Call + Put for protection.
    Defined-risk, profits in range-bound markets.
    """
    name = "iron_condor"
    description = "Sell OTM spreads on both sides — defined-risk range play"

    def analyse(self, chain: OptionChain, price_history: pd.DataFrame, has_position: bool) -> OptionsSignal:
        if has_position:
            return self._hold("Position already open")

        closes = price_history["close"].values
        if len(closes) < 30:
            return self._hold("Insufficient data")

        recent_vol = float(np.std(np.diff(np.log(closes[-20:]))) * np.sqrt(252))
        adr = float(np.mean(np.abs(np.diff(closes[-20:])) / closes[-21:-1]))

        # Best in low-ADR, mean-reverting environments
        if adr > 0.015:
            return self._hold("Market too volatile for iron condor")

        atm = chain.get_atm_strike()
        cfg_step = {"NIFTY": 50, "BANKNIFTY": 100}.get(chain.underlying, 50)

        sell_call = atm + cfg_step * 3
        buy_call = atm + cfg_step * 5
        sell_put = atm - cfg_step * 3
        buy_put = atm - cfg_step * 5

        sc = chain.get_strike(sell_call, "call")
        bc = chain.get_strike(buy_call, "call")
        sp = chain.get_strike(sell_put, "put")
        bp = chain.get_strike(buy_put, "put")

        if not all([sc, bc, sp, bp]):
            return self._hold("Required strikes not available")

        confidence = min(0.75, 0.5 + (0.015 - adr) * 20)
        ls = sc.lot_size

        legs = [
            OptionLeg(strike=sell_call, option_type="call", side="short", lots=1, lot_size=ls, entry_premium=sc.premium),
            OptionLeg(strike=buy_call, option_type="call", side="long", lots=1, lot_size=ls, entry_premium=bc.premium),
            OptionLeg(strike=sell_put, option_type="put", side="short", lots=1, lot_size=ls, entry_premium=sp.premium),
            OptionLeg(strike=buy_put, option_type="put", side="long", lots=1, lot_size=ls, entry_premium=bp.premium),
        ]
        return OptionsSignal(action="open", legs=legs, confidence=confidence, reason=f"Low ADR {adr:.3%}")


class BullCallSpreadStrategy(BaseOptionsStrategy):
    """Buy ATM/ITM Call, sell OTM Call. Defined-risk bullish play."""
    name = "bull_call_spread"
    description = "Buy lower CE + sell higher CE — bullish with defined risk"

    def analyse(self, chain: OptionChain, price_history: pd.DataFrame, has_position: bool) -> OptionsSignal:
        if has_position:
            return self._hold("Position already open")

        closes = price_history["close"].values
        if len(closes) < 30:
            return self._hold("Insufficient data")

        ema_short = float(pd.Series(closes).ewm(span=8).mean().iloc[-1])
        ema_long = float(pd.Series(closes).ewm(span=21).mean().iloc[-1])
        rsi = _rsi(closes, 14)

        # Bullish: short EMA above long EMA, RSI > 50
        if ema_short <= ema_long or rsi < 50:
            return self._hold("Not bullish enough")

        atm = chain.get_atm_strike()
        step = {"NIFTY": 50, "BANKNIFTY": 100}.get(chain.underlying, 50)

        buy_strike = atm
        sell_strike = atm + step * 4

        buy_c = chain.get_strike(buy_strike, "call")
        sell_c = chain.get_strike(sell_strike, "call")

        if not buy_c or not sell_c:
            return self._hold("Strikes not found")

        confidence = min(0.8, 0.4 + (ema_short - ema_long) / ema_long * 10 + (rsi - 50) / 100)
        ls = buy_c.lot_size

        legs = [
            OptionLeg(strike=buy_strike, option_type="call", side="long", lots=1, lot_size=ls, entry_premium=buy_c.premium),
            OptionLeg(strike=sell_strike, option_type="call", side="short", lots=1, lot_size=ls, entry_premium=sell_c.premium),
        ]
        return OptionsSignal(action="open", legs=legs, confidence=confidence, reason=f"Bullish EMA + RSI {rsi:.0f}")


class BearPutSpreadStrategy(BaseOptionsStrategy):
    """Buy ATM/ITM Put, sell OTM Put. Defined-risk bearish play."""
    name = "bear_put_spread"
    description = "Buy higher PE + sell lower PE — bearish with defined risk"

    def analyse(self, chain: OptionChain, price_history: pd.DataFrame, has_position: bool) -> OptionsSignal:
        if has_position:
            return self._hold("Position already open")

        closes = price_history["close"].values
        if len(closes) < 30:
            return self._hold("Insufficient data")

        ema_short = float(pd.Series(closes).ewm(span=8).mean().iloc[-1])
        ema_long = float(pd.Series(closes).ewm(span=21).mean().iloc[-1])
        rsi = _rsi(closes, 14)

        if ema_short >= ema_long or rsi > 50:
            return self._hold("Not bearish enough")

        atm = chain.get_atm_strike()
        step = {"NIFTY": 50, "BANKNIFTY": 100}.get(chain.underlying, 50)

        buy_strike = atm
        sell_strike = atm - step * 4

        buy_p = chain.get_strike(buy_strike, "put")
        sell_p = chain.get_strike(sell_strike, "put")

        if not buy_p or not sell_p:
            return self._hold("Strikes not found")

        confidence = min(0.8, 0.4 + (ema_long - ema_short) / ema_long * 10 + (50 - rsi) / 100)
        ls = buy_p.lot_size

        legs = [
            OptionLeg(strike=buy_strike, option_type="put", side="long", lots=1, lot_size=ls, entry_premium=buy_p.premium),
            OptionLeg(strike=sell_strike, option_type="put", side="short", lots=1, lot_size=ls, entry_premium=sell_p.premium),
        ]
        return OptionsSignal(action="open", legs=legs, confidence=confidence, reason=f"Bearish EMA + RSI {rsi:.0f}")


class IronButterflyStrategy(BaseOptionsStrategy):
    """Sell ATM Call + Put, buy OTM Call + Put. Max profit at ATM expiry."""
    name = "iron_butterfly"
    description = "Sell ATM + buy wings — max profit if spot stays at ATM"

    def analyse(self, chain: OptionChain, price_history: pd.DataFrame, has_position: bool) -> OptionsSignal:
        if has_position:
            return self._hold("Position already open")

        closes = price_history["close"].values
        if len(closes) < 30:
            return self._hold("Insufficient data")

        recent_vol = float(np.std(np.diff(np.log(closes[-20:]))) * np.sqrt(252))
        adr = float(np.mean(np.abs(np.diff(closes[-20:])) / closes[-21:-1]))

        if adr > 0.012:
            return self._hold("Too volatile for iron butterfly")

        atm = chain.get_atm_strike()
        step = {"NIFTY": 50, "BANKNIFTY": 100}.get(chain.underlying, 50)
        wing_dist = step * 4

        sell_call = chain.get_strike(atm, "call")
        sell_put = chain.get_strike(atm, "put")
        buy_call = chain.get_strike(atm + wing_dist, "call")
        buy_put = chain.get_strike(atm - wing_dist, "put")

        if not all([sell_call, sell_put, buy_call, buy_put]):
            return self._hold("Required strikes not found")

        confidence = min(0.7, 0.45 + (0.012 - adr) * 25)
        ls = sell_call.lot_size

        legs = [
            OptionLeg(strike=atm, option_type="call", side="short", lots=1, lot_size=ls, entry_premium=sell_call.premium),
            OptionLeg(strike=atm, option_type="put", side="short", lots=1, lot_size=ls, entry_premium=sell_put.premium),
            OptionLeg(strike=atm + wing_dist, option_type="call", side="long", lots=1, lot_size=ls, entry_premium=buy_call.premium),
            OptionLeg(strike=atm - wing_dist, option_type="put", side="long", lots=1, lot_size=ls, entry_premium=buy_put.premium),
        ]
        return OptionsSignal(action="open", legs=legs, confidence=confidence, reason=f"Very low ADR {adr:.3%}")


def _rsi(closes: np.ndarray, period: int = 14) -> float:
    if len(closes) < period + 1:
        return 50.0
    deltas = np.diff(closes[-(period + 1):])
    gains = np.mean(deltas[deltas > 0]) if np.any(deltas > 0) else 0
    losses = -np.mean(deltas[deltas < 0]) if np.any(deltas < 0) else 0
    if losses == 0:
        return 100.0
    rs = gains / losses
    return 100 - (100 / (1 + rs))


OPTIONS_STRATEGY_REGISTRY: dict[str, tuple[type, str]] = {
    "long_straddle": (LongStraddleStrategy, "Buy ATM CE + PE — profits from big moves"),
    "short_straddle": (ShortStraddleStrategy, "Sell ATM CE + PE — profits from sideways markets"),
    "long_strangle": (LongStrangleStrategy, "Buy OTM CE + PE — cheaper directional bet"),
    "iron_condor": (IronCondorStrategy, "Sell OTM spreads — defined-risk range play"),
    "bull_call_spread": (BullCallSpreadStrategy, "Buy-sell call spread — bullish defined risk"),
    "bear_put_spread": (BearPutSpreadStrategy, "Buy-sell put spread — bearish defined risk"),
    "iron_butterfly": (IronButterflyStrategy, "Sell ATM + buy wings — max profit at spot"),
}
