"""
============================================================
 STOCK INTELLIGENCE SCANNER
 Technical + Fundamental Analysis Engine
 Hourly Email Reports | Multi-Timeframe Signals
============================================================
"""

import yfinance as yf
import pandas as pd
import numpy as np
import smtplib
import schedule
import time
import logging
import json
import os
from datetime import datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from jinja2 import Template
from config import Config

# ─── Logging Setup (Windows Unicode-safe) ───────────────────────────────────
import sys

class SafeStreamHandler(logging.StreamHandler):
    """Strips emoji/special chars that Windows cp1252 terminal can't display."""
    def emit(self, record):
        try:
            msg = self.format(record)
            msg_safe = msg.encode("cp1252", errors="replace").decode("cp1252")
            self.stream.write(msg_safe + self.terminator)
            self.flush()
        except Exception:
            self.handleError(record)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler("logs/scanner.log", encoding="utf-8"),
        SafeStreamHandler(sys.stdout)
    ]
)
log = logging.getLogger(__name__)


# ════════════════════════════════════════════════════════════════════════════
#  TECHNICAL ANALYSIS ENGINE
# ════════════════════════════════════════════════════════════════════════════

def compute_rsi(series, period=14):
    delta = series.diff()
    gain = delta.clip(lower=0).rolling(period).mean()
    loss = -delta.clip(upper=0).rolling(period).mean()
    rs = gain / loss.replace(0, np.nan)
    return 100 - (100 / (1 + rs))


def compute_macd(series, fast=12, slow=26, signal=9):
    ema_fast = series.ewm(span=fast, adjust=False).mean()
    ema_slow = series.ewm(span=slow, adjust=False).mean()
    macd = ema_fast - ema_slow
    signal_line = macd.ewm(span=signal, adjust=False).mean()
    histogram = macd - signal_line
    return macd, signal_line, histogram


def compute_bollinger(series, period=20, std=2):
    sma = series.rolling(period).mean()
    stddev = series.rolling(period).std()
    upper = sma + std * stddev
    lower = sma - std * stddev
    return upper, sma, lower


def compute_stochastic(high, low, close, k=14, d=3):
    lowest_low = low.rolling(k).min()
    highest_high = high.rolling(k).max()
    k_pct = 100 * (close - lowest_low) / (highest_high - lowest_low).replace(0, np.nan)
    d_pct = k_pct.rolling(d).mean()
    return k_pct, d_pct


def compute_atr(high, low, close, period=14):
    tr = pd.concat([
        high - low,
        (high - close.shift()).abs(),
        (low - close.shift()).abs()
    ], axis=1).max(axis=1)
    return tr.rolling(period).mean()


def compute_adx(high, low, close, period=14):
    tr = pd.concat([
        high - low,
        (high - close.shift()).abs(),
        (low - close.shift()).abs()
    ], axis=1).max(axis=1)
    dm_plus = high.diff().clip(lower=0)
    dm_minus = (-low.diff()).clip(lower=0)
    atr = tr.rolling(period).mean()
    di_plus = 100 * dm_plus.rolling(period).mean() / atr.replace(0, np.nan)
    di_minus = 100 * dm_minus.rolling(period).mean() / atr.replace(0, np.nan)
    dx = 100 * (di_plus - di_minus).abs() / (di_plus + di_minus).replace(0, np.nan)
    adx = dx.rolling(period).mean()
    return adx, di_plus, di_minus


def compute_obv(close, volume):
    direction = np.sign(close.diff()).fillna(0)
    return (direction * volume).cumsum()


def compute_vwap(high, low, close, volume):
    typical = (high + low + close) / 3
    return (typical * volume).cumsum() / volume.cumsum()


def compute_ichimoku(high, low):
    tenkan = (high.rolling(9).max() + low.rolling(9).min()) / 2
    kijun = (high.rolling(26).max() + low.rolling(26).min()) / 2
    senkou_a = ((tenkan + kijun) / 2).shift(26)
    senkou_b = ((high.rolling(52).max() + low.rolling(52).min()) / 2).shift(26)
    return tenkan, kijun, senkou_a, senkou_b


def get_technical_signals(df, timeframe="daily"):
    """
    Compute all 10 technical indicators and return signal scores.
    Returns: dict of signals and overall score (0-100)
    """
    close = df["Close"]
    high = df["High"]
    low = df["Low"]
    volume = df["Volume"]

    signals = {}
    score = 0
    max_score = 0

    # 1. RSI
    rsi = compute_rsi(close).iloc[-1]
    signals["RSI"] = round(rsi, 2)
    max_score += 10
    if rsi < 30:
        signals["RSI_signal"] = "BUY"
        score += 10
    elif rsi > 70:
        signals["RSI_signal"] = "SELL"
        score += 0
    else:
        signals["RSI_signal"] = "HOLD"
        score += 5

    # 2. MACD
    macd, signal_line, hist = compute_macd(close)
    signals["MACD"] = round(macd.iloc[-1], 4)
    signals["MACD_Signal"] = round(signal_line.iloc[-1], 4)
    max_score += 10
    if hist.iloc[-1] > 0 and hist.iloc[-2] <= 0:
        signals["MACD_signal"] = "BUY"
        score += 10
    elif hist.iloc[-1] < 0 and hist.iloc[-2] >= 0:
        signals["MACD_signal"] = "SELL"
        score += 0
    elif hist.iloc[-1] > 0:
        signals["MACD_signal"] = "HOLD"
        score += 6
    else:
        signals["MACD_signal"] = "HOLD"
        score += 4

    # 3. Bollinger Bands
    upper, mid, lower_bb = compute_bollinger(close)
    c = close.iloc[-1]
    signals["BB_Upper"] = round(upper.iloc[-1], 2)
    signals["BB_Lower"] = round(lower_bb.iloc[-1], 2)
    max_score += 10
    if c <= lower_bb.iloc[-1]:
        signals["BB_signal"] = "BUY"
        score += 10
    elif c >= upper.iloc[-1]:
        signals["BB_signal"] = "SELL"
        score += 0
    else:
        signals["BB_signal"] = "HOLD"
        score += 5

    # 4. EMA Crossover (20/50/200)
    ema20 = close.ewm(span=20).mean().iloc[-1]
    ema50 = close.ewm(span=50).mean().iloc[-1]
    ema200 = close.ewm(span=200).mean().iloc[-1]
    signals["EMA20"] = round(ema20, 2)
    signals["EMA50"] = round(ema50, 2)
    signals["EMA200"] = round(ema200, 2)
    max_score += 10
    if c > ema20 > ema50 > ema200:
        signals["EMA_signal"] = "BUY"
        score += 10
    elif c < ema20 < ema50 < ema200:
        signals["EMA_signal"] = "SELL"
        score += 0
    else:
        signals["EMA_signal"] = "HOLD"
        score += 5

    # 5. VWAP
    vwap = compute_vwap(high, low, close, volume).iloc[-1]
    signals["VWAP"] = round(vwap, 2)
    max_score += 10
    if c > vwap * 1.01:
        signals["VWAP_signal"] = "BUY"
        score += 10
    elif c < vwap * 0.99:
        signals["VWAP_signal"] = "SELL"
        score += 0
    else:
        signals["VWAP_signal"] = "HOLD"
        score += 5

    # 6. Stochastic
    k, d = compute_stochastic(high, low, close)
    signals["Stoch_K"] = round(k.iloc[-1], 2)
    signals["Stoch_D"] = round(d.iloc[-1], 2)
    max_score += 10
    if k.iloc[-1] < 20 and k.iloc[-1] > d.iloc[-1]:
        signals["Stoch_signal"] = "BUY"
        score += 10
    elif k.iloc[-1] > 80 and k.iloc[-1] < d.iloc[-1]:
        signals["Stoch_signal"] = "SELL"
        score += 0
    else:
        signals["Stoch_signal"] = "HOLD"
        score += 5

    # 7. ATR (volatility info — not directional)
    atr = compute_atr(high, low, close).iloc[-1]
    signals["ATR"] = round(atr, 2)
    atr_pct = (atr / c) * 100
    signals["ATR_%"] = round(atr_pct, 2)
    max_score += 10
    if atr_pct < 2:
        signals["ATR_signal"] = "LOW_VOL"
        score += 7
    elif atr_pct > 5:
        signals["ATR_signal"] = "HIGH_VOL"
        score += 3
    else:
        signals["ATR_signal"] = "NORMAL"
        score += 5

    # 8. ADX
    adx, di_plus, di_minus = compute_adx(high, low, close)
    signals["ADX"] = round(adx.iloc[-1], 2)
    max_score += 10
    if adx.iloc[-1] > 25 and di_plus.iloc[-1] > di_minus.iloc[-1]:
        signals["ADX_signal"] = "BUY"
        score += 10
    elif adx.iloc[-1] > 25 and di_minus.iloc[-1] > di_plus.iloc[-1]:
        signals["ADX_signal"] = "SELL"
        score += 0
    else:
        signals["ADX_signal"] = "HOLD"
        score += 5

    # 9. Ichimoku
    tenkan, kijun, sen_a, sen_b = compute_ichimoku(high, low)
    signals["Ichimoku_Tenkan"] = round(tenkan.iloc[-1], 2)
    signals["Ichimoku_Kijun"] = round(kijun.iloc[-1], 2)
    max_score += 10
    if c > sen_a.iloc[-1] and c > sen_b.iloc[-1] and tenkan.iloc[-1] > kijun.iloc[-1]:
        signals["Ichimoku_signal"] = "BUY"
        score += 10
    elif c < sen_a.iloc[-1] and c < sen_b.iloc[-1]:
        signals["Ichimoku_signal"] = "SELL"
        score += 0
    else:
        signals["Ichimoku_signal"] = "HOLD"
        score += 5

    # 10. OBV
    obv = compute_obv(close, volume)
    obv_trend = obv.diff(5).iloc[-1]
    signals["OBV_Trend"] = "Rising" if obv_trend > 0 else "Falling"
    max_score += 10
    if obv_trend > 0:
        signals["OBV_signal"] = "BUY"
        score += 10
    else:
        signals["OBV_signal"] = "SELL"
        score += 0

    tech_score = round((score / max_score) * 100, 1)
    signals["tech_score"] = tech_score
    return signals


# ════════════════════════════════════════════════════════════════════════════
#  FUNDAMENTAL ANALYSIS ENGINE
# ════════════════════════════════════════════════════════════════════════════

def get_fundamental_signals(ticker_obj):
    """
    Compute all 10 fundamental indicators and return signal scores.
    """
    signals = {}
    score = 0
    max_score = 0

    info = ticker_obj.info

    def safe_get(key, default=None):
        return info.get(key, default)

    # 1. P/E Ratio
    pe = safe_get("trailingPE")
    signals["PE_Ratio"] = round(pe, 2) if pe else "N/A"
    max_score += 10
    if pe and pe < 15:
        signals["PE_signal"] = "BUY"
        score += 10
    elif pe and pe > 30:
        signals["PE_signal"] = "SELL"
        score += 2
    elif pe:
        signals["PE_signal"] = "HOLD"
        score += 6
    else:
        signals["PE_signal"] = "N/A"
        score += 5

    # 2. P/B Ratio
    pb = safe_get("priceToBook")
    signals["PB_Ratio"] = round(pb, 2) if pb else "N/A"
    max_score += 10
    if pb and pb < 1.5:
        signals["PB_signal"] = "BUY"
        score += 10
    elif pb and pb > 5:
        signals["PB_signal"] = "SELL"
        score += 2
    elif pb:
        signals["PB_signal"] = "HOLD"
        score += 6
    else:
        signals["PB_signal"] = "N/A"
        score += 5

    # 3. EPS Growth
    eps_current = safe_get("trailingEps")
    eps_forward = safe_get("forwardEps")
    signals["EPS_Current"] = eps_current
    signals["EPS_Forward"] = eps_forward
    max_score += 10
    if eps_current and eps_forward:
        eps_growth = ((eps_forward - eps_current) / abs(eps_current)) * 100
        signals["EPS_Growth_%"] = round(eps_growth, 2)
        if eps_growth > 15:
            signals["EPS_signal"] = "BUY"
            score += 10
        elif eps_growth < 0:
            signals["EPS_signal"] = "SELL"
            score += 2
        else:
            signals["EPS_signal"] = "HOLD"
            score += 6
    else:
        signals["EPS_Growth_%"] = "N/A"
        signals["EPS_signal"] = "N/A"
        score += 5

    # 4. Revenue Growth
    rev_growth = safe_get("revenueGrowth")
    signals["Revenue_Growth_%"] = round(rev_growth * 100, 2) if rev_growth else "N/A"
    max_score += 10
    if rev_growth and rev_growth > 0.10:
        signals["Revenue_signal"] = "BUY"
        score += 10
    elif rev_growth and rev_growth < 0:
        signals["Revenue_signal"] = "SELL"
        score += 2
    elif rev_growth:
        signals["Revenue_signal"] = "HOLD"
        score += 6
    else:
        signals["Revenue_signal"] = "N/A"
        score += 5

    # 5. Debt-to-Equity
    de = safe_get("debtToEquity")
    signals["Debt_to_Equity"] = round(de / 100, 2) if de else "N/A"
    max_score += 10
    if de and de < 50:
        signals["DE_signal"] = "BUY"
        score += 10
    elif de and de > 200:
        signals["DE_signal"] = "SELL"
        score += 2
    elif de:
        signals["DE_signal"] = "HOLD"
        score += 6
    else:
        signals["DE_signal"] = "N/A"
        score += 5

    # 6. Free Cash Flow Yield
    fcf = safe_get("freeCashflow")
    market_cap = safe_get("marketCap")
    max_score += 10
    if fcf and market_cap:
        fcf_yield = (fcf / market_cap) * 100
        signals["FCF_Yield_%"] = round(fcf_yield, 2)
        if fcf_yield > 5:
            signals["FCF_signal"] = "BUY"
            score += 10
        elif fcf_yield < 0:
            signals["FCF_signal"] = "SELL"
            score += 2
        else:
            signals["FCF_signal"] = "HOLD"
            score += 6
    else:
        signals["FCF_Yield_%"] = "N/A"
        signals["FCF_signal"] = "N/A"
        score += 5

    # 7. ROE
    roe = safe_get("returnOnEquity")
    signals["ROE_%"] = round(roe * 100, 2) if roe else "N/A"
    max_score += 10
    if roe and roe > 0.15:
        signals["ROE_signal"] = "BUY"
        score += 10
    elif roe and roe < 0:
        signals["ROE_signal"] = "SELL"
        score += 2
    elif roe:
        signals["ROE_signal"] = "HOLD"
        score += 6
    else:
        signals["ROE_signal"] = "N/A"
        score += 5

    # 8. Profit Margin
    margin = safe_get("profitMargins")
    gross = safe_get("grossMargins")
    signals["Net_Margin_%"] = round(margin * 100, 2) if margin else "N/A"
    signals["Gross_Margin_%"] = round(gross * 100, 2) if gross else "N/A"
    max_score += 10
    if margin and margin > 0.15:
        signals["Margin_signal"] = "BUY"
        score += 10
    elif margin and margin < 0:
        signals["Margin_signal"] = "SELL"
        score += 2
    elif margin:
        signals["Margin_signal"] = "HOLD"
        score += 6
    else:
        signals["Margin_signal"] = "N/A"
        score += 5

    # 9. Current Ratio
    curr_ratio = safe_get("currentRatio")
    signals["Current_Ratio"] = round(curr_ratio, 2) if curr_ratio else "N/A"
    max_score += 10
    if curr_ratio and curr_ratio > 2:
        signals["CR_signal"] = "BUY"
        score += 10
    elif curr_ratio and curr_ratio < 1:
        signals["CR_signal"] = "SELL"
        score += 2
    elif curr_ratio:
        signals["CR_signal"] = "HOLD"
        score += 6
    else:
        signals["CR_signal"] = "N/A"
        score += 5

    # 10. Analyst Target Price
    current_price = safe_get("currentPrice") or safe_get("regularMarketPrice")
    target = safe_get("targetMeanPrice")
    max_score += 10
    if current_price and target:
        upside = ((target - current_price) / current_price) * 100
        signals["Analyst_Target"] = round(target, 2)
        signals["Analyst_Upside_%"] = round(upside, 2)
        if upside > 15:
            signals["Analyst_signal"] = "BUY"
            score += 10
        elif upside < -10:
            signals["Analyst_signal"] = "SELL"
            score += 0
        else:
            signals["Analyst_signal"] = "HOLD"
            score += 5
    else:
        signals["Analyst_Target"] = "N/A"
        signals["Analyst_Upside_%"] = "N/A"
        signals["Analyst_signal"] = "N/A"
        score += 5

    fund_score = round((score / max_score) * 100, 1)
    signals["fund_score"] = fund_score
    return signals


# ════════════════════════════════════════════════════════════════════════════
#  COMPOSITE SIGNAL & TIMEFRAME LOGIC
# ════════════════════════════════════════════════════════════════════════════

def classify_signal(score):
    if score >= 65:
        return "BUY"
    elif score <= 40:
        return "SELL"
    else:
        return "HOLD"


def get_timeframe_signal(tech, fund, timeframe):
    """Weight tech vs fundamental differently per timeframe."""
    if timeframe == "daily":
        composite = tech * 0.80 + fund * 0.20
    elif timeframe == "weekly":
        composite = tech * 0.60 + fund * 0.40
    else:  # monthly
        composite = tech * 0.35 + fund * 0.65
    return round(composite, 1), classify_signal(composite)


def scan_stock(ticker_symbol):
    """Full scan of one ticker: fetch data, run all indicators, generate signals."""
    try:
        log.info(f"  Scanning {ticker_symbol}...")
        ticker = yf.Ticker(ticker_symbol)
        df = ticker.history(period="2y", interval="1d")
        if df.empty or len(df) < 60:
            log.warning(f"  {ticker_symbol}: Insufficient data, skipping.")
            return None

        info = ticker.info
        current_price = info.get("currentPrice") or info.get("regularMarketPrice") or df["Close"].iloc[-1]
        prev_close = df["Close"].iloc[-2]
        change_pct = round(((current_price - prev_close) / prev_close) * 100, 2)

        tech = get_technical_signals(df)
        fund = get_fundamental_signals(ticker)

        ts, td = get_timeframe_signal(tech["tech_score"], fund["fund_score"], "daily")
        ws, wd = get_timeframe_signal(tech["tech_score"], fund["fund_score"], "weekly")
        ms, md = get_timeframe_signal(tech["tech_score"], fund["fund_score"], "monthly")

        # Key trigger summary
        buy_triggers = []
        sell_triggers = []
        for key in ["RSI_signal", "MACD_signal", "BB_signal", "EMA_signal", "VWAP_signal",
                    "Stoch_signal", "ADX_signal", "Ichimoku_signal", "OBV_signal"]:
            val = tech.get(key, "HOLD")
            name = key.replace("_signal", "")
            if val == "BUY":
                buy_triggers.append(name)
            elif val == "SELL":
                sell_triggers.append(name)

        for key in ["PE_signal", "PB_signal", "EPS_signal", "Revenue_signal",
                    "DE_signal", "FCF_signal", "ROE_signal", "Margin_signal",
                    "CR_signal", "Analyst_signal"]:
            val = fund.get(key, "N/A")
            name = key.replace("_signal", "")
            if val == "BUY":
                buy_triggers.append(f"F:{name}")
            elif val == "SELL":
                sell_triggers.append(f"F:{name}")

        return {
            "ticker": ticker_symbol,
            "name": info.get("shortName", ticker_symbol)[:22],
            "sector": info.get("sector", "N/A"),
            "price": round(current_price, 2),
            "change_pct": change_pct,
            "market_cap": info.get("marketCap"),
            "tech_score": tech["tech_score"],
            "fund_score": fund["fund_score"],
            "daily_score": ts,
            "daily_signal": td,
            "weekly_score": ws,
            "weekly_signal": wd,
            "monthly_score": ms,
            "monthly_signal": md,
            "buy_triggers": buy_triggers[:5],
            "sell_triggers": sell_triggers[:5],
            "rsi": tech.get("RSI"),
            "macd": tech.get("MACD"),
            "atr_pct": tech.get("ATR_%"),
            "adx": tech.get("ADX"),
            "pe": fund.get("PE_Ratio"),
            "roe": fund.get("ROE_%"),
            "revenue_growth": fund.get("Revenue_Growth_%"),
            "analyst_upside": fund.get("Analyst_Upside_%"),
            "tech_details": tech,
            "fund_details": fund,
        }
    except Exception as e:
        log.error(f"  Error scanning {ticker_symbol}: {e}")
        return None


def run_full_scan(tickers):
    """Scan all tickers and return sorted results."""
    log.info(f"━━━ Starting scan of {len(tickers)} tickers ━━━")
    results = []
    for t in tickers:
        r = scan_stock(t)
        if r:
            results.append(r)
    results.sort(key=lambda x: x["daily_score"], reverse=True)
    log.info(f"━━━ Scan complete: {len(results)} results ━━━")
    return results


# ════════════════════════════════════════════════════════════════════════════
#  EMAIL ENGINE
# ════════════════════════════════════════════════════════════════════════════

EMAIL_TEMPLATE = """
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Stock Intelligence Report</title>
<style>
  @import url('https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@400;600&family=Space+Grotesk:wght@400;500;700&display=swap');

  * { margin: 0; padding: 0; box-sizing: border-box; }
  body {
    background: #0a0e1a;
    color: #e0e8ff;
    font-family: 'Space Grotesk', sans-serif;
    padding: 20px;
  }
  .container { max-width: 900px; margin: 0 auto; }

  /* ── Header ── */
  .header {
    background: linear-gradient(135deg, #0d1b3e 0%, #1a2a5e 50%, #0d1b3e 100%);
    border: 1px solid #2a3a7e;
    border-radius: 12px;
    padding: 28px 32px;
    margin-bottom: 24px;
    position: relative;
    overflow: hidden;
  }
  .header::before {
    content: '';
    position: absolute; top: 0; left: 0; right: 0; height: 2px;
    background: linear-gradient(90deg, #00d4ff, #7c3aed, #00d4ff);
  }
  .header-top { display: flex; justify-content: space-between; align-items: flex-start; }
  .brand { font-family: 'IBM Plex Mono', monospace; }
  .brand-title { font-size: 22px; font-weight: 600; color: #00d4ff; letter-spacing: 2px; }
  .brand-sub { font-size: 12px; color: #6b7aaa; margin-top: 4px; }
  .timestamp { text-align: right; font-family: 'IBM Plex Mono', monospace; font-size: 12px; color: #4a5a8a; }
  .stats-row { display: flex; gap: 20px; margin-top: 20px; }
  .stat-box { background: rgba(0,212,255,0.07); border: 1px solid rgba(0,212,255,0.2); border-radius: 8px; padding: 12px 16px; flex: 1; }
  .stat-val { font-size: 22px; font-weight: 700; color: #00d4ff; font-family: 'IBM Plex Mono', monospace; }
  .stat-lbl { font-size: 11px; color: #4a5a8a; margin-top: 2px; text-transform: uppercase; letter-spacing: 1px; }

  /* ── Section Headers ── */
  .section-title {
    font-size: 13px; font-weight: 600; text-transform: uppercase;
    letter-spacing: 2px; color: #7c3aed; margin: 24px 0 12px;
    display: flex; align-items: center; gap: 10px;
  }
  .section-title::after { content: ''; flex: 1; height: 1px; background: rgba(124,58,237,0.3); }

  /* ── Main Table ── */
  table { width: 100%; border-collapse: collapse; margin-bottom: 24px; }
  thead th {
    background: #0d1b3e; color: #4a5a8a;
    font-size: 11px; font-weight: 600; text-transform: uppercase; letter-spacing: 1px;
    padding: 10px 12px; text-align: left; border-bottom: 1px solid #1e2d5e;
    font-family: 'IBM Plex Mono', monospace;
  }
  tbody tr { border-bottom: 1px solid #111827; transition: background 0.15s; }
  tbody tr:hover { background: rgba(255,255,255,0.02); }
  tbody td { padding: 11px 12px; font-size: 13px; vertical-align: middle; }

  .ticker-cell { font-family: 'IBM Plex Mono', monospace; font-weight: 600; color: #e0e8ff; font-size: 14px; }
  .name-cell { color: #6b7aaa; font-size: 12px; }
  .price-cell { font-family: 'IBM Plex Mono', monospace; font-weight: 600; }
  .change-pos { color: #10b981; }
  .change-neg { color: #ef4444; }

  /* Signal badges */
  .badge {
    display: inline-block; padding: 3px 10px; border-radius: 20px;
    font-size: 11px; font-weight: 700; letter-spacing: 1px;
    font-family: 'IBM Plex Mono', monospace;
  }
  .badge-buy { background: rgba(16,185,129,0.15); color: #10b981; border: 1px solid rgba(16,185,129,0.3); }
  .badge-sell { background: rgba(239,68,68,0.15); color: #ef4444; border: 1px solid rgba(239,68,68,0.3); }
  .badge-hold { background: rgba(245,158,11,0.15); color: #f59e0b; border: 1px solid rgba(245,158,11,0.3); }

  /* Score bar */
  .score-wrap { display: flex; align-items: center; gap: 8px; min-width: 90px; }
  .score-bar-bg { flex: 1; height: 5px; background: #1e2d5e; border-radius: 3px; overflow: hidden; }
  .score-bar { height: 100%; border-radius: 3px; }
  .score-bar-buy { background: #10b981; }
  .score-bar-hold { background: #f59e0b; }
  .score-bar-sell { background: #ef4444; }
  .score-num { font-family: 'IBM Plex Mono', monospace; font-size: 12px; color: #6b7aaa; width: 30px; }

  /* Triggers */
  .trigger-tag {
    display: inline-block; background: rgba(0,212,255,0.08);
    border: 1px solid rgba(0,212,255,0.15); border-radius: 4px;
    padding: 1px 6px; font-size: 10px; color: #00a8cc; margin: 1px;
    font-family: 'IBM Plex Mono', monospace;
  }

  /* ── Top Picks ── */
  .picks-grid { display: grid; grid-template-columns: repeat(5, 1fr); gap: 10px; margin-bottom: 24px; }
  .pick-card {
    background: linear-gradient(135deg, #0d1b3e, #141f3e);
    border: 1px solid #1e2d5e; border-radius: 10px; padding: 14px;
  }
  .pick-card.top { border-color: rgba(0,212,255,0.4); background: linear-gradient(135deg, #0a1f3a, #0d2244); }
  .pick-ticker { font-family: 'IBM Plex Mono', monospace; font-size: 14px; font-weight: 700; color: #00d4ff; }
  .pick-price { font-size: 12px; color: #6b7aaa; margin-top: 2px; }
  .pick-score { font-size: 22px; font-weight: 700; margin-top: 8px; color: #e0e8ff; }
  .pick-label { font-size: 10px; color: #4a5a8a; text-transform: uppercase; letter-spacing: 1px; }

  /* ── Footer ── */
  .footer {
    border-top: 1px solid #1e2d5e; padding-top: 16px; margin-top: 16px;
    color: #2a3a6e; font-size: 11px; text-align: center; line-height: 1.8;
  }
  .disclaimer {
    background: rgba(239,68,68,0.05); border: 1px solid rgba(239,68,68,0.15);
    border-radius: 8px; padding: 10px 14px; margin-bottom: 16px;
    font-size: 11px; color: #6b2020;
  }
</style>
</head>
<body>
<div class="container">

<!-- ── Header ── -->
<div class="header">
  <div class="header-top">
    <div class="brand">
      <div class="brand-title">⚡ STOCK INTELLIGENCE</div>
      <div class="brand-sub">Technical + Fundamental Analysis Engine</div>
    </div>
    <div class="timestamp">
      <div>{{ scan_time }}</div>
      <div style="margin-top:4px;color:#2a3a6e;">Next scan in ~1 hour</div>
    </div>
  </div>
  <div class="stats-row">
    <div class="stat-box">
      <div class="stat-val">{{ total_scanned }}</div>
      <div class="stat-lbl">Stocks Scanned</div>
    </div>
    <div class="stat-box">
      <div class="stat-val" style="color:#10b981">{{ buy_count }}</div>
      <div class="stat-lbl">Buy Signals</div>
    </div>
    <div class="stat-box">
      <div class="stat-val" style="color:#f59e0b">{{ hold_count }}</div>
      <div class="stat-lbl">Hold Signals</div>
    </div>
    <div class="stat-box">
      <div class="stat-val" style="color:#ef4444">{{ sell_count }}</div>
      <div class="stat-lbl">Sell Signals</div>
    </div>
    <div class="stat-box">
      <div class="stat-val" style="color:#7c3aed">20</div>
      <div class="stat-lbl">Indicators</div>
    </div>
  </div>
</div>

<!-- ── Top 5 Picks ── -->
<div class="section-title">🏆 Top 5 Picks of the Hour</div>
<div class="picks-grid">
{% for s in top5 %}
<div class="pick-card {{ 'top' if loop.index == 1 else '' }}">
  <div class="pick-ticker">{{ s.ticker }}</div>
  <div class="pick-price">${{ s.price }} | {{ '+' if s.change_pct > 0 else '' }}{{ s.change_pct }}%</div>
  <div class="pick-score">{{ s.daily_score }}</div>
  <div class="pick-label">Daily Score</div>
  <div style="margin-top:8px">
    <span class="badge badge-{{ s.daily_signal.lower() }}">{{ s.daily_signal }}</span>
  </div>
</div>
{% endfor %}
</div>

<!-- ── Short-Term Table (Daily/Weekly) ── -->
<div class="section-title">⚡ Short-Term Opportunities</div>
<table>
  <thead>
    <tr>
      <th>Ticker</th>
      <th>Price</th>
      <th>Chg%</th>
      <th>Daily</th>
      <th>Weekly</th>
      <th>Tech Score</th>
      <th>Fund Score</th>
      <th>RSI</th>
      <th>ADX</th>
      <th>Buy Triggers</th>
    </tr>
  </thead>
  <tbody>
{% for s in short_term %}
<tr>
  <td>
    <div class="ticker-cell">{{ s.ticker }}</div>
    <div class="name-cell">{{ s.name }}</div>
  </td>
  <td class="price-cell">${{ s.price }}</td>
  <td class="{{ 'change-pos' if s.change_pct > 0 else 'change-neg' }}">
    {{ '+' if s.change_pct > 0 else '' }}{{ s.change_pct }}%
  </td>
  <td><span class="badge badge-{{ s.daily_signal.lower() }}">{{ s.daily_signal }} {{ s.daily_score }}</span></td>
  <td><span class="badge badge-{{ s.weekly_signal.lower() }}">{{ s.weekly_signal }} {{ s.weekly_score }}</span></td>
  <td>
    <div class="score-wrap">
      <div class="score-bar-bg"><div class="score-bar score-bar-{{ 'buy' if s.tech_score >= 65 else ('sell' if s.tech_score <= 40 else 'hold') }}" style="width:{{ s.tech_score }}%"></div></div>
      <div class="score-num">{{ s.tech_score }}</div>
    </div>
  </td>
  <td>
    <div class="score-wrap">
      <div class="score-bar-bg"><div class="score-bar score-bar-{{ 'buy' if s.fund_score >= 65 else ('sell' if s.fund_score <= 40 else 'hold') }}" style="width:{{ s.fund_score }}%"></div></div>
      <div class="score-num">{{ s.fund_score }}</div>
    </div>
  </td>
  <td style="font-family:'IBM Plex Mono',monospace;font-size:12px;">{{ s.rsi }}</td>
  <td style="font-family:'IBM Plex Mono',monospace;font-size:12px;">{{ s.adx }}</td>
  <td>{% for t in s.buy_triggers %}<span class="trigger-tag">{{ t }}</span>{% endfor %}</td>
</tr>
{% endfor %}
  </tbody>
</table>

<!-- ── Long-Term Table (Monthly) ── -->
<div class="section-title">📈 Long-Term Opportunities</div>
<table>
  <thead>
    <tr>
      <th>Ticker</th>
      <th>Price</th>
      <th>Monthly Signal</th>
      <th>Fund Score</th>
      <th>P/E</th>
      <th>ROE%</th>
      <th>Rev Growth%</th>
      <th>Analyst Upside%</th>
      <th>Sector</th>
    </tr>
  </thead>
  <tbody>
{% for s in long_term %}
<tr>
  <td>
    <div class="ticker-cell">{{ s.ticker }}</div>
    <div class="name-cell">{{ s.name }}</div>
  </td>
  <td class="price-cell">${{ s.price }}</td>
  <td><span class="badge badge-{{ s.monthly_signal.lower() }}">{{ s.monthly_signal }} {{ s.monthly_score }}</span></td>
  <td>
    <div class="score-wrap">
      <div class="score-bar-bg"><div class="score-bar score-bar-{{ 'buy' if s.fund_score >= 65 else ('sell' if s.fund_score <= 40 else 'hold') }}" style="width:{{ s.fund_score }}%"></div></div>
      <div class="score-num">{{ s.fund_score }}</div>
    </div>
  </td>
  <td style="font-family:'IBM Plex Mono',monospace;font-size:12px;">{{ s.pe }}</td>
  <td style="font-family:'IBM Plex Mono',monospace;font-size:12px;">{{ s.roe }}</td>
  <td style="font-family:'IBM Plex Mono',monospace;font-size:12px;">{{ s.revenue_growth }}</td>
  <td style="font-family:'IBM Plex Mono',monospace;font-size:12px;color:{% if s.analyst_upside != 'N/A' and s.analyst_upside > 15 %}#10b981{% elif s.analyst_upside != 'N/A' and s.analyst_upside < 0 %}#ef4444{% else %}#6b7aaa{% endif %}">
    {% if s.analyst_upside != 'N/A' %}+{{ s.analyst_upside }}%{% else %}N/A{% endif %}
  </td>
  <td style="font-size:12px;color:#6b7aaa;">{{ s.sector }}</td>
</tr>
{% endfor %}
  </tbody>
</table>

<!-- ── Watchlist Alerts ── -->
{% if watchlist_alerts %}
<div class="section-title">🔔 Watchlist Alerts</div>
<table>
  <thead>
    <tr><th>Ticker</th><th>Price</th><th>Alert</th><th>Score</th><th>Signal</th></tr>
  </thead>
  <tbody>
{% for s in watchlist_alerts %}
<tr>
  <td class="ticker-cell">{{ s.ticker }}</td>
  <td class="price-cell">${{ s.price }}</td>
  <td style="color:#f59e0b;font-size:12px;">{{ s.alert }}</td>
  <td>{{ s.daily_score }}</td>
  <td><span class="badge badge-{{ s.daily_signal.lower() }}">{{ s.daily_signal }}</span></td>
</tr>
{% endfor %}
  </tbody>
</table>
{% endif %}

<!-- ── Disclaimer ── -->
<div class="disclaimer">
  ⚠️ <strong>Disclaimer:</strong> This report is generated by an automated algorithm for informational purposes only.
  It does not constitute financial advice. Past performance is not indicative of future results.
  Always conduct your own research and consult a licensed financial advisor before making investment decisions.
</div>
<div class="footer">
  Stock Intelligence Scanner • Generated {{ scan_time }} • 10 Technical + 10 Fundamental Indicators<br>
  Timeframes: Daily (Short-Term) | Weekly (Swing) | Monthly (Long-Term)
</div>

</div>
</body>
</html>
"""


def send_email(results, cfg):
    """Render and send the HTML email report."""
    if not results:
        log.warning("No results to send.")
        return

    scan_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    buy_count = sum(1 for r in results if r["daily_signal"] == "BUY")
    hold_count = sum(1 for r in results if r["daily_signal"] == "HOLD")
    sell_count = sum(1 for r in results if r["daily_signal"] == "SELL")

    short_term = [r for r in results if r["daily_signal"] in ("BUY", "HOLD")][:15]
    long_term = sorted(results, key=lambda x: x["monthly_score"], reverse=True)[:10]
    top5 = results[:5]

    # Watchlist alerts: significant signal changes
    watchlist_alerts = []
    for r in results:
        if r["ticker"] in cfg.WATCHLIST:
            if r["daily_signal"] == "BUY" and r["daily_score"] >= 70:
                r["alert"] = f"Strong BUY — score {r['daily_score']}"
                watchlist_alerts.append(r)
            elif r["daily_signal"] == "SELL" and r["daily_score"] <= 35:
                r["alert"] = f"Strong SELL — score {r['daily_score']}"
                watchlist_alerts.append(r)

    tmpl = Template(EMAIL_TEMPLATE)
    html = tmpl.render(
        scan_time=scan_time,
        total_scanned=len(results),
        buy_count=buy_count,
        hold_count=hold_count,
        sell_count=sell_count,
        top5=top5,
        short_term=short_term,
        long_term=long_term,
        watchlist_alerts=watchlist_alerts,
    )

    # Support both single EMAIL_TO and multiple EMAIL_RECIPIENTS
    recipients = getattr(cfg, "EMAIL_RECIPIENTS", None)
    if not recipients:
        recipients = [cfg.EMAIL_TO]
    # Remove blanks and duplicates
    recipients = list(dict.fromkeys([r.strip() for r in recipients if r.strip()]))

    msg = MIMEMultipart("alternative")
    msg["Subject"] = f"[Stock Intelligence] {scan_time} | {buy_count} BUY | {hold_count} HOLD | {sell_count} SELL"
    msg["From"] = cfg.EMAIL_FROM
    msg["To"] = ", ".join(recipients)
    msg.attach(MIMEText(html, "html"))

    try:
        with smtplib.SMTP_SSL(cfg.SMTP_HOST, cfg.SMTP_PORT) as server:
            server.login(cfg.SMTP_USER, cfg.SMTP_PASS)
            server.sendmail(cfg.EMAIL_FROM, recipients, msg.as_string())
        log.info(f"[OK] Email sent to {len(recipients)} recipient(s): {', '.join(recipients)}")
    except Exception as e:
        log.error(f"[ERROR] Email failed: {e}")

    # Save HTML report locally (UTF-8 for Windows)
    report_path = f"output/report_{datetime.now().strftime('%Y%m%d_%H%M')}.html"
    with open(report_path, "w", encoding="utf-8") as f:
        f.write(html)
    log.info("[OK] Report saved: " + report_path)


# ════════════════════════════════════════════════════════════════════════════
#  SCHEDULER
# ════════════════════════════════════════════════════════════════════════════

def job():
    cfg = Config()
    log.info("═" * 60)
    log.info(" STOCK INTELLIGENCE SCANNER — HOURLY JOB STARTED")
    log.info("═" * 60)
    results = run_full_scan(cfg.TICKERS)
    send_email(results, cfg)
    log.info("═" * 60)


if __name__ == "__main__":
    log.info("🚀 Stock Intelligence Scanner starting...")
    job()  # Run immediately on start
    schedule.every().hour.at(":00").do(job)
    log.info("⏰ Scheduled to run every hour. Press Ctrl+C to stop.")
    while True:
        schedule.run_pending()
        time.sleep(30)
