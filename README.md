# FinMarket Intelligence Platform

A full-stack financial intelligence platform with real-time data pipelines,
ML forecasting, RAG-powered AI analysis, and automated alerting.
Built entirely on free infrastructure.

![Python](https://img.shields.io/badge/Python-3.11-blue)
![FastAPI](https://img.shields.io/badge/FastAPI-0.111-green)
![AWS](https://img.shields.io/badge/AWS-RDS%20%7C%20S3%20%7C%20CloudWatch-orange)
![Docker](https://img.shields.io/badge/Docker-Compose-blue)
![Prophet](https://img.shields.io/badge/ML-Prophet%20%7C%20XGBoost-purple)
![LangGraph](https://img.shields.io/badge/AI-LangGraph%20%7C%20Groq%20LLaMA3-red)

## Live Demo
> Dashboard: [coming in Phase 5]
> API Docs: [coming in Phase 6]

## What This Platform Does

FinMarket Intelligence is a production-grade financial analysis system that:

- Collects real stock prices, news, and sentiment data automatically every few minutes
- Runs ML models daily to forecast prices (Prophet) and predict direction (XGBoost)
- Detects unusual price and volume events using statistical anomaly detection
- Scores news article sentiment using transformer-based NLP models
- Embeds all news into vector representations for semantic search
- Answers natural language questions about any tracked stock using RAG + LLaMA3

Ask it: *"Should I be worried about Apple given recent news and price trends?"*
It retrieves real data from all sources and generates a grounded answer.

## Architecture

```
Real financial data (yfinance, NewsAPI, RSS feeds, Alpha Vantage)
        ↓
Kafka event stream (Docker KRaft — no Zookeeper)
        ↓
ClickHouse (price time-series) + PostgreSQL/RDS (news, forecasts, vectors)
        ↓
ML Pipeline (runs automatically via Celery):
  Prophet        → 7-day price forecast with confidence intervals
  XGBoost        → buy/sell direction signal + confidence score
  spaCy NER      → extracts ticker mentions from news headlines
  sentence-transformers → sentiment scoring -1.0 to +1.0
  statsmodels    → z-score anomaly detection (price + volume)
  pgvector       → 384-dim semantic embeddings
        ↓
RAG + AI Layer:
  pgvector semantic search → finds relevant articles for any query
  LangGraph agent          → 3-node workflow (intent → retrieve → generate)
  Groq LLaMA3-70b          → generates grounded natural language answers
        ↓
REST API (FastAPI) → Streamlit Dashboard (Phase 5)
```

## Tech Stack

| Layer | Technology |
|---|---|
| API | FastAPI 0.111, Pydantic v2, SQLAlchemy 2.0 |
| Primary DB | AWS RDS PostgreSQL 16 + pgvector extension |
| Time-series DB | ClickHouse 23.8 (Docker) |
| Cache / Broker | Redis 7 (Docker) + Celery 5.4 |
| Message Queue | Kafka 7.5 (KRaft mode, Docker) |
| ML Forecasting | Prophet 1.1.5, XGBoost 2.0.3 |
| ML NLP | spaCy 3.7.5, sentence-transformers 2.7.0 |
| ML Stats | statsmodels 0.14.2, scikit-learn 1.4.2 |
| ML Tracking | MLflow 2.13.0 |
| AI Agent | LangGraph 0.0.69, LangChain 0.2.0 |
| LLM | Groq API — LLaMA3-70b (free tier) |
| Vector Search | pgvector (cosine similarity) |
| Storage | AWS S3 (raw data + MLflow artifacts) |
| Monitoring | AWS CloudWatch, Flower (Celery UI), MLflow UI |
| CI/CD | GitHub Actions → AWS ECR → EC2 (Phase 6) |
| Dashboard | Streamlit Community Cloud (Phase 5) |

## Data Sources (all free)

| Source | Data | Key required |
|---|---|---|
| yfinance | OHLCV stock prices | No |
| yfinance `.news` | Company news headlines | No |
| NewsAPI | Financial news articles | Yes (free tier) |
| Reuters RSS | Business headlines | No |
| Yahoo Finance RSS | Market news | No |
| MarketWatch RSS | Market news | No |
| Alpha Vantage | News + NLP sentiment | Yes (free tier) |
| Groq API | LLaMA3-70b LLM | Yes (free tier) |

## Project Phases

| Phase | What | Status |
|---|---|---|
| Phase 1 | Foundation — FastAPI, AWS RDS, Docker, tests | ✅ Complete |
| Phase 2 | Data ingestion — prices, news, sentiment pipeline | ✅ Complete |
| Phase 3 | ML models — forecasting, NLP, anomaly detection | ✅ Complete |
| Phase 4 | RAG + LangGraph AI agent + Groq LLM | ✅ Complete |
| Phase 5 | Streamlit dashboard + email alerts | 🔄 In progress |
| Phase 6 | Deploy to AWS EC2 + GitHub Actions CI/CD | ⏳ Upcoming |

## Getting Started

### Prerequisites
- Docker Desktop
- Python 3.11
- AWS account (free tier)
- Groq API key (free at console.groq.com)
- NewsAPI key (free at newsapi.org)

### Local Development

```bash
# Clone the repository
git clone https://github.com/Palash0306/FinMarket-Intelligence-Platform.git
cd FinMarket-Intelligence-Platform

# Set up environment
cp .env.example .env
# Edit .env — add RDS URL, AWS keys, Groq key, NewsAPI key

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

# Seed 1 year of historical price data into ClickHouse
python scripts/seed_prices.py

# Start all services
docker compose up --build
```

### Verify everything is running

```bash
# System health (checks RDS + ClickHouse)
curl http://localhost:8000/health

# Stock list
curl http://localhost:8000/api/stocks/

# Live price
curl http://localhost:8000/api/prices/AAPL

# Generate ML forecast (runs in background)
curl -X POST http://localhost:8000/api/forecasts/AAPL/run

# Get forecast after ~30 seconds
curl http://localhost:8000/api/forecasts/AAPL

# Latest news
curl http://localhost:8000/api/news/AAPL

# Sentiment chart data
curl "http://localhost:8000/api/news/AAPL/sentiment?days=7"

# Anomaly alerts
curl http://localhost:8000/api/anomalies/AAPL

# AI chat (requires Groq API key)
curl -X POST http://localhost:8000/api/chat/ \
  -H "Content-Type: application/json" \
  -d '{"question": "What is the current price and outlook for Apple?"}'
```

### Local monitoring dashboards

| URL | What you see |
|---|---|
| http://localhost:8000/docs | All 22 API endpoints (Swagger UI) |
| http://localhost:5555 | Flower — Celery task monitor |
| http://localhost:5001 | MLflow — ML experiment tracker |
| http://localhost:8090 | Kafka UI — message stream monitor |
| http://localhost:8080 | Adminer — database browser (RDS + local) |
| http://localhost:8123/play | ClickHouse SQL playground |

### Run tests

```bash
pytest tests/ -v
```

## Automated Data Pipeline

Everything below runs automatically while Docker is running:

```
Every 5 min    yfinance → Kafka → ClickHouse ohlcv
Every 15 min   ClickHouse → z-score analysis → RDS anomalies
Every 30 min   NewsAPI + RSS → Kafka → RDS news_articles
               spaCy NER → fills ticker_symbols column
               sentence-transformers → fills sentiment_score
Every hour     Alpha Vantage → Kafka → RDS sentiment signals
               sentence-transformers → pgvector embeddings
Daily 9am UTC  Prophet → 7-day price forecast → RDS forecasts
               XGBoost → buy/sell direction signal → RDS forecasts
```

## AWS Infrastructure (all free tier)

| Service | Purpose | Free tier |
|---|---|---|
| RDS t3.micro | PostgreSQL 16 + pgvector | 750 hrs/month, 12 months |
| EC2 t2.micro | FastAPI + Celery (Phase 6) | 750 hrs/month, 12 months |
| S3 | Raw data archive + MLflow model artifacts | 5 GB forever |
| SES | Alert emails (Phase 5) | 3,000/month forever |
| CloudWatch | Structured JSON logs + metrics | 5 GB forever |

## API Reference

### System
| Method | Endpoint | Description |
|---|---|---|
| GET | /health | RDS + ClickHouse health check |
| GET | /docs | Interactive Swagger UI |

### Stocks
| Method | Endpoint | Description |
|---|---|---|
| GET | /api/stocks/ | All tracked stocks |
| GET | /api/stocks/{symbol} | One stock |
| POST | /api/stocks/ | Add stock |
| PATCH | /api/stocks/{symbol} | Update stock |
| DELETE | /api/stocks/{symbol} | Deactivate stock |

### Prices
| Method | Endpoint | Description |
|---|---|---|
| GET | /api/prices/ | All stocks latest prices |
| GET | /api/prices/{symbol} | Latest price + change % |
| GET | /api/prices/{symbol}/history | Historical candles |
| GET | /api/prices/{symbol}/summary | Daily aggregates |

### News + Sentiment
| Method | Endpoint | Description |
|---|---|---|
| GET | /api/news/ | Latest news all stocks |
| GET | /api/news/{symbol} | News for one stock |
| GET | /api/news/{symbol}/sentiment | Sentiment time series |

### ML Forecasts
| Method | Endpoint | Description |
|---|---|---|
| GET | /api/forecasts/ | All stocks latest signals |
| GET | /api/forecasts/{symbol} | 7-day forecast + direction signal |
| POST | /api/forecasts/{symbol}/run | Trigger forecast now |

### Anomalies
| Method | Endpoint | Description |
|---|---|---|
| GET | /api/anomalies/ | All recent anomalies |
| GET | /api/anomalies/{symbol} | Anomalies for one stock |

### AI Chat
| Method | Endpoint | Description |
|---|---|---|
| POST | /api/chat/ | Ask any financial question |
| GET | /api/chat/health | Check Groq API configuration |

## AI Chat Examples

```bash
# Price and forecast
curl -X POST http://localhost:8000/api/chat/ \
  -H "Content-Type: application/json" \
  -d '{"question": "What is the forecast for NVIDIA this week?"}'

# News analysis
curl -X POST http://localhost:8000/api/chat/ \
  -H "Content-Type: application/json" \
  -d '{"question": "What is the latest news about Goldman Sachs?"}'

# Anomaly check
curl -X POST http://localhost:8000/api/chat/ \
  -H "Content-Type: application/json" \
  -d '{"question": "Any unusual market activity today?"}'

# Full analysis
curl -X POST http://localhost:8000/api/chat/ \
  -H "Content-Type: application/json" \
  -d '{"question": "Give me a full analysis of Apple stock"}'
```

## Key Technical Decisions

**Why two databases?**
ClickHouse is a columnar database optimised for time-series aggregations.
`AVG(close) per hour for 90 days` across millions of rows runs in milliseconds.
Postgres handles text search, relationships, and the pgvector extension for RAG.
Each database does what it is best at.

**Why Kafka between fetchers and storage?**
Decoupling. If ClickHouse is temporarily slow, messages queue in Kafka safely.
The fetcher never blocks. No data loss during restarts or slowdowns.

**Why pre-compute ML forecasts instead of computing on request?**
Prophet training takes 30 seconds per symbol — 10 symbols = 5 minutes total.
Celery runs this daily at 9am UTC silently in the background.
The API reads pre-computed results in 30ms. Users never wait.

**Why RAG instead of just asking the LLM directly?**
LLMs have knowledge cutoffs and cannot access real-time data.
RAG retrieves your actual current data first, then passes it as context.
The LLM answers using real prices, real news, real forecasts — not hallucinations.

**Why LangGraph instead of a single LLM call?**
A single call cannot decide which data sources to query based on the question.
LangGraph's graph structure enables: extract intent → route to correct tools →
retrieve relevant data → generate grounded answer. Each step is testable.

**Why Groq instead of OpenAI?**
Groq's free tier provides 14,400 requests per day with LLaMA3-70b.
No credit card required. Fast inference. Sufficient quality for financial Q&A.
This project is built entirely on free infrastructure — Groq fits that constraint.

## What I Built and Learned

**Architecture:**
- Decoupled data pipeline (Celery + Kafka) fully separate from API layer
- Two-database strategy (ClickHouse + Postgres) with right tool for each data type
- RAG pattern: vector embeddings → semantic retrieval → LLM generation
- LangGraph multi-node agent workflow with intent classification

**ML Engineering:**
- Time-series forecasting with Prophet (confidence intervals, seasonality)
- Binary classification with XGBoost (no shuffle split, feature engineering)
- Statistical anomaly detection with rolling z-scores
- Zero-shot sentiment scoring with sentence-transformers
- Named entity recognition with spaCy for ticker extraction
- Experiment tracking with MLflow (params, metrics, model artifacts)

**Infrastructure:**
- AWS free tier: RDS PostgreSQL with pgvector, S3, CloudWatch
- Docker Compose with 10 services (Kafka, ClickHouse, Redis, MLflow, Flower)
- Structured JSON logging with CloudWatch integration
- Alembic database migrations with version control

**API Design:**
- 22 REST endpoints across 6 domains
- Global error handling middleware with request ID tracking
- Pydantic v2 schemas for request validation and response shaping
- FastAPI BackgroundTasks for non-blocking ML model execution

## Tracked Stocks

| Symbol | Company | Sector |
|---|---|---|
| AAPL | Apple Inc. | Technology |
| MSFT | Microsoft Corporation | Technology |
| GOOGL | Alphabet Inc. | Technology |
| NVDA | NVIDIA Corporation | Technology |
| META | Meta Platforms Inc. | Technology |
| JPM | JPMorgan Chase | Finance |
| GS | Goldman Sachs | Finance |
| JNJ | Johnson & Johnson | Healthcare |
| XOM | Exxon Mobil | Energy |
| AMZN | Amazon.com Inc. | Consumer |

## Author

Palash Aggarwal — [GitHub](https://github.com/Palash0306)
