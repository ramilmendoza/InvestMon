# InvestMon

Flask-based web application for stock monitoring and personal investment portfolio tracking, focused on the Philippine Stock Exchange (PSE).

## Tech Stack

- **Backend:** Python 3, Flask, Flask-SQLAlchemy, pandas, plotly
- **Frontend:** Jinja2 templates, Bootstrap 5.3, custom CSS (cyberpunk/neon theme)
- **Database:** Two SQLite databases — `stocks.db` (market data, raw SQL via pandas) and `instance/investments.db` (portfolio/investments, SQLAlchemy ORM)
- **Currency:** Philippine Peso (₱)

## Project Structure

- `investmon.py` — Main application (all routes, models, and logic in a single file)
- `templates/` — Jinja2 templates (base.html for layout, investments/, portfolio/ subdirs)
- `uploads/` — CSV files uploaded for stock data import
- `stocks.db` — OHLCV stock price data
- `instance/investments.db` — Investment accounts, transactions, portfolio holdings

## Running

```bash
pip install Flask pandas plotly Flask-SQLAlchemy
python investmon.py
```

Runs on `http://localhost:5000` with debug mode enabled.

## Database

**stocks.db** — Table `stocks` with columns: symbol, date, open, high, low, close, volume, nfb_nfs. Unique on (symbol, date).

**investments.db** — Three ORM models:
- `Investment` — account/platform info, amounts, profit/loss
- `Transaction` — dated amounts linked to an Investment
- `Portfolio` — stock holdings with shares, prices, linked to Investment

## Key Routes

- `/` — Stock dashboard
- `/upload` — CSV import (format: Symbol, Date MM/DD/YYYY, Open, High, Low, Close, Volume, NFB/NFS)
- `/symbol/<symbol>` — Stock detail with Plotly charts
- `/investments` — Investment account management
- `/portfolio` — Portfolio holdings with P/L calculations
- `/my-stocks` — Aggregated stock holdings view

## Conventions

- All code in a single `investmon.py` file (no separate models/routes modules)
- SQLAlchemy ORM for investments, raw SQL via pandas for stock data
- Template inheritance from `base.html`
- Dark/light theme toggle stored in cookies/localStorage
