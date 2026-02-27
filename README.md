# ⚡ Stock Intelligence Scanner

**20-Indicator Stock Scanning Engine** — Hourly email reports covering 10 Technical + 10 Fundamental indicators across Daily, Weekly, and Monthly timeframes.

---

## 📦 Setup (5 minutes)

### 1. Install dependencies
```bash
pip install -r requirements.txt
```

### 2. Configure your email
Edit `config.py` and set:
```python
SMTP_USER = "your_gmail@gmail.com"
SMTP_PASS = "your_app_password"        # Gmail App Password (not your login password)
EMAIL_FROM = "your_gmail@gmail.com"
EMAIL_TO   = "recipient@gmail.com"     # Where reports are sent (can be same address)
```

**Gmail App Password setup:**
1. Go to [myaccount.google.com/apppasswords](https://myaccount.google.com/apppasswords)
2. Select app: **Mail** | Device: **Other (Custom name)** → "StockScanner"
3. Copy the 16-character password into `SMTP_PASS`

> **Other email providers:** Change `SMTP_HOST` and `SMTP_PORT` in `config.py`

### 3. Customize your tickers
Edit the `TICKERS` list in `config.py` to scan the stocks you want.

### 4. Run the scanner
```bash
python scanner.py
```

The scanner will:
- Run immediately on start
- Send an email report
- Then run every hour automatically

---

## 📊 What You Get in Every Email

### 📈 20 Indicators Per Stock

**Top 10 Technical Indicators:**
| # | Indicator | Signal Logic |
|---|-----------|-------------|
| 1 | RSI (14) | < 30 = BUY, > 70 = SELL |
| 2 | MACD | Crossover above/below signal line |
| 3 | Bollinger Bands | Price at lower/upper band |
| 4 | EMA 20/50/200 | Price & EMA alignment (trend) |
| 5 | VWAP | Price above/below VWAP |
| 6 | Stochastic (14,3) | < 20 bullish cross = BUY |
| 7 | ATR | Volatility classification |
| 8 | ADX (14) | Trend strength + DI direction |
| 9 | Ichimoku Cloud | Price above/below cloud |
| 10 | OBV | Rising/falling volume pressure |

**Top 10 Fundamental Indicators:**
| # | Indicator | Signal Logic |
|---|-----------|-------------|
| 1 | P/E Ratio | < 15 = BUY, > 30 = SELL |
| 2 | P/B Ratio | < 1.5 = BUY, > 5 = SELL |
| 3 | EPS Growth | > 15% = BUY, < 0% = SELL |
| 4 | Revenue Growth | > 10% = BUY, < 0% = SELL |
| 5 | Debt/Equity | < 0.5 = BUY, > 2 = SELL |
| 6 | FCF Yield | > 5% = BUY, < 0% = SELL |
| 7 | ROE | > 15% = BUY, < 0% = SELL |
| 8 | Profit Margin | > 15% = BUY, < 0% = SELL |
| 9 | Current Ratio | > 2 = BUY, < 1 = SELL |
| 10 | Analyst Target | > 15% upside = BUY |

### ⏱️ Timeframe Signals

| Timeframe | Use Case | Tech Weight | Fund Weight |
|-----------|----------|------------|------------|
| **Daily** | Day/swing trading (1–5 days) | 80% | 20% |
| **Weekly** | Swing trading (1–4 weeks) | 60% | 40% |
| **Monthly** | Long-term investing (1–12 months) | 35% | 65% |

### 📧 Email Contents
- **Stats Header**: Total scanned, BUY/HOLD/SELL counts
- **Top 5 Picks**: Highest scoring stocks of the hour
- **Short-Term Table**: Daily/Weekly signals with RSI, ADX, buy triggers
- **Long-Term Table**: Monthly signals with fundamentals
- **Watchlist Alerts**: Special alerts for your watchlist stocks

---

## ⚙️ Advanced Configuration

### Environment variables (alternative to editing config.py)
```bash
export SMTP_USER="your_email@gmail.com"
export SMTP_PASS="your_app_password"
export EMAIL_FROM="your_email@gmail.com"
export EMAIL_TO="recipient@gmail.com"
python scanner.py
```

### Run as a background service (Linux/Mac)
```bash
nohup python scanner.py > logs/scanner.log 2>&1 &
```

### Run as a Windows service
Use [NSSM](https://nssm.cc/) or Task Scheduler to run `python scanner.py` at startup.

---

## 📁 Project Structure
```
stock_scanner/
├── scanner.py          ← Main application
├── config.py           ← Your settings (edit this!)
├── requirements.txt    ← Python dependencies
├── README.md           ← This file
├── logs/
│   └── scanner.log     ← Runtime logs
└── output/
    └── report_*.html   ← Saved HTML reports (one per scan)
```

---

## ⚠️ Disclaimer
This tool is for **informational and educational purposes only**. It does not constitute financial advice. Always conduct your own research and consult a licensed financial advisor before making investment decisions. Past performance is not indicative of future results.

---

## 💡 Tips
- Start with 30–50 tickers for faster scans (~1–2 min)
- 100+ tickers may take 5–10 min per scan due to API rate limits
- All HTML reports are saved in `/output` for offline review
- Check `logs/scanner.log` for debugging
