# FinMarket Intelligence Platform

A full-stack financial intelligence platform with real-time data pipelines,
ML forecasting, RAG-powered AI analysis, and automated alerting.
Built entirely on free infrastructure.

![Python](https://img.shields.io/badge/Python-3.11-blue)
![FastAPI](https://img.shields.io/badge/FastAPI-0.111-green)
![AWS](https://img.shields.io/badge/AWS-RDS%20%7C%20S3%20%7C%20CloudWatch-orange)
![Docker](https://img.shields.io/badge/Docker-Compose-blue)
![Prophet](https://img.shields.io/badge/ML-Prophet%20%7C%20XGBoost-purple)
![spaCy](https://img.shields.io/badge/NLP-spaCy%20%7C%20sentence--transformers-green)

## Live Demo
> Dashboard: [coming in Phase 5]
> API Docs: [coming in Phase 6]

## Architecture
Real financial data (yfinance, NewsAPI, RSS feeds, Alpha Vantage)
↓
Kafka event stream (local Docker — KRaft mode, no Zookeeper)
↓
ClickHouse (price time-series) + PostgreSQL/RDS (news, forecasts)
↓
ML models:
Prophet        → 7-day price forecast with confidence intervals
XGBoost        → buy/sell direction signal + confidence score
spaCy NER      → extracts ticker symbols from news headlines
sentence-transformers → sentiment scoring -1.0 to +1.0
statsmodels    → z-score anomaly detection (price + volume)
pgvector       → 384-dim semantic embeddings for RAG
↓
RAG layer (pgvector semantic search + LangGraph agent
+ Groq LLaMA3 — free cloud LLM)
↓
Streamlit dashboard + REST API (FastAPI)

## Tech Stack

| Layer | Technology |
|---|---|
| API | FastAPI 0.111, Pydantic v2, SQLAlchemy 2.0 |
| Primary DB | AWS RDS PostgreSQL 16 + pgvector extension |
| Time-series DB | ClickHouse 23.8 (Docker local) |
| Cache / Broker | Redis 7 (Docker) + Celery 5.4 |
| Message Queue | Kafka 7.5 (KRaft mode, Docker) |
| ML Forecasting | Prophet 1.1.5, XGBoost 2.0.3 |
| ML NLP | spaCy 3.7.5, sentence-transformers 2.7.0 |
| ML Stats | statsmodels 0.14.2, scikit-learn 1.4.2 |
| ML Tracking | MLflow 2.13.0 |
| AI Layer | LangGraph, Groq API (LLaMA3), pgvector RAG |
| Storage | AWS S3 (raw data archive + ML artifacts) |
| Monitoring | AWS CloudWatch, Flower (Celery UI) |
| CI/CD | GitHub Actions → AWS ECR → EC2 |
| Dashboard | Streamlit Community Cloud |

## Data Sources (all free)

| Source | Data | Method |
|---|---|---|
| yfinance | OHLCV stock prices | No API key needed |
| NewsAPI | Financial news articles | 100 req/day free tier |
| Reuters / Yahoo / MarketWatch | News headlines | Free RSS feeds |
| Alpha Vantage | News + sentiment | 25 req/day free tier |
| yfinance `.news` | Company news + sentiment | No API key needed |

## Project Phases

| Phase | What | Status |
|---|---|---|
| Phase 1 | Foundation, FastAPI, AWS RDS, Docker | ✅ Complete |
| Phase 2 | Data ingestion — prices, news, sentiment | ✅ Complete |
| Phase 3 | ML models — forecasting, NLP, anomalies | ✅ Complete |
| Phase 4 | RAG + LangGraph AI agent | 🔄 In progress |
| Phase 5 | Streamlit dashboard + alerts | ⏳ Upcoming |
| Phase 6 | Deploy to AWS EC2 + CI/CD | ⏳ Upcoming |

## Getting Started

### Prerequisites
- Docker Desktop
- Python 3.11
- AWS account (free tier)

### Local Development

```bash
# Clone the repository
git clone https://github.com/Palash0306/FinMarket-Intelligence-Platform.git
cd FinMarket-Intelligence-Platform

# Set up environment
cp .env.example .env
# Edit .env with your credentials (RDS, AWS keys, NewsAPI key)

# Create virtual environment
python3.11 -m venv .venv
source .venv/bin/activate      # Windows: .venv\Scripts\Activate.ps1

# Install dependencies
pip install -r requirements.txt

# Download spaCy language model
python -m spacy download en_core_web_sm

# Run database migrations
alembic upgrade head

# Seed initial stock data (10 companies)
python scripts/seed_stocks.py

# Seed historical price data into ClickHouse (1 year)
python scripts/seed_prices.py

# Start all services
docker compose up --build
```

### Verify everything works

```bash
# Health check
curl http://localhost:8000/health

# Stock data
curl http://localhost:8000/api/stocks/

# Live prices (after seed_prices.py)
curl http://localhost:8000/api/prices/AAPL

# 7-day forecast (after running models)
curl -X POST http://localhost:8000/api/forecasts/AAPL/run
curl http://localhost:8000/api/forecasts/AAPL

# News + sentiment
curl http://localhost:8000/api/news/AAPL
curl http://localhost:8000/api/news/AAPL/sentiment

# Anomalies
curl http://localhost:8000/api/anomalies/AAPL
```

### Monitoring UIs (while Docker is running)

| URL | What |
|---|---|
| http://localhost:8000/docs | FastAPI Swagger UI |
| http://localhost:5555 | Flower — Celery task monitor |
| http://localhost:5001 | MLflow — ML experiment tracking |
| http://localhost:8090 | Kafka UI — message stream monitor |
| http://localhost:8080 | Adminer — database browser |
| http://localhost:8123/play | ClickHouse SQL playground |

### Run tests

```bash
pytest tests/ -v
```

## AWS Infrastructure (all free tier)

| Service | Purpose | Free Tier |
|---|---|---|
| RDS t3.micro | PostgreSQL 16 + pgvector | 750 hrs/month, 12 months |
| EC2 t2.micro | FastAPI + Celery (Phase 6) | 750 hrs/month, 12 months |
| S3 | Raw data archive + MLflow artifacts | 5GB forever |
| SES | Alert emails (Phase 5) | 3,000/month forever |
| CloudWatch | Structured JSON logs | 5GB forever |

## Automated Data Pipeline
Every 5 min:   yfinance → Kafka → ClickHouse (prices)
Every 15 min:  ClickHouse → z-score → RDS anomalies
Every 30 min:  NewsAPI + RSS → Kafka → RDS news_articles
spaCy NER → fills ticker_symbols column
sentence-transformers → fills sentiment_score
Every hour:    Alpha Vantage → Kafka → RDS sentiment signals
sentence-transformers → pgvector embeddings
Daily 9am UTC: Prophet → 7-day price forecast → RDS
XGBoost → buy/sell signal → RDS

## API Endpoints

### System
| Method | Endpoint | Description |
|---|---|---|
| GET | /health | Database + ClickHouse health check |
| GET | /docs | Interactive API documentation |

### Stocks
| Method | Endpoint | Description |
|---|---|---|
| GET | /api/stocks/ | List all tracked stocks |
| GET | /api/stocks/{symbol} | Get one stock |
| POST | /api/stocks/ | Add new stock |
| PATCH | /api/stocks/{symbol} | Update stock |
| DELETE | /api/stocks/{symbol} | Deactivate stock |

### Prices
| Method | Endpoint | Description |
|---|---|---|
| GET | /api/prices/ | All stocks latest prices |
| GET | /api/prices/{symbol} | Latest price + change |
| GET | /api/prices/{symbol}/history | Historical candles |
| GET | /api/prices/{symbol}/summary | Daily aggregates |

### News + Sentiment
| Method | Endpoint | Description |
|---|---|---|
| GET | /api/news/ | Latest news all stocks |
| GET | /api/news/{symbol} | News for one stock |
| GET | /api/news/{symbol}/sentiment | Sentiment time series |

### Forecasts
| Method | Endpoint | Description |
|---|---|---|
| GET | /api/forecasts/ | All stocks latest signals |
| GET | /api/forecasts/{symbol} | 7-day forecast + signal |
| POST | /api/forecasts/{symbol}/run | Trigger forecast now |

### Anomalies
| Method | Endpoint | Description |
|---|---|---|
| GET | /api/anomalies/ | All recent anomalies |
| GET | /api/anomalies/{symbol} | Anomalies for one stock |

## Key Technical Decisions

**Why ClickHouse for prices, not Postgres?**
ClickHouse is a columnar database optimised for time-series aggregations.
`AVG(close) per hour for 90 days` across millions of rows runs in milliseconds.
The same query in Postgres would take seconds.

**Why Kafka between fetchers and storage?**
Decoupling. If ClickHouse is temporarily slow, messages queue in Kafka safely.
The fetcher never waits. The consumer processes at its own pace. No data loss.

**Why pre-compute ML forecasts with Celery instead of computing on request?**
Prophet training takes 20-30 seconds per symbol. 10 symbols = 5 minutes.
Celery runs this daily at 9am UTC. API reads pre-computed results in 30ms.

**Why sentence-transformers for sentiment instead of keywords?**
Keywords misfire. "Apple beats cancer diagnosis" triggers bullish on "beats".
sentence-transformers understands context and meaning — not just word matching.

## What I Built

- Decoupled data pipeline (Celery + Kafka) separate from API layer
- 4 ML models running on automated schedules
- Semantic search infrastructure (pgvector) for Phase 4 RAG
- 18 REST API endpoints across 5 domains
- Full observability: CloudWatch logs, MLflow experiments, Flower tasks
- AWS free tier infrastructure for all production components

## Author
Palash Aggarwal — [GitHub](https://github.com/Palash0306)