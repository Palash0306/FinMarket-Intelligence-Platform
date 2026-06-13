# FinMarket Intelligence Platform

A full-stack financial intelligence platform with real-time data pipelines,
ML forecasting, RAG-powered AI analysis, and an interactive web dashboard.
Built entirely on free infrastructure.

![Python](https://img.shields.io/badge/Python-3.11-blue)
![FastAPI](https://img.shields.io/badge/FastAPI-0.111-green)
![Streamlit](https://img.shields.io/badge/Dashboard-Streamlit-red)
![AWS](https://img.shields.io/badge/AWS-RDS%20%7C%20S3%20%7C%20CloudWatch-orange)
![Docker](https://img.shields.io/badge/Docker-Compose-blue)
![LangGraph](https://img.shields.io/badge/AI-LangGraph%20%7C%20Groq%20LLaMA3-purple)

## Live Demo
> Dashboard: [coming in Phase 6 — Streamlit Cloud]
> API Docs: [coming in Phase 6 — AWS EC2]

## What This Platform Does

FinMarket Intelligence is a production-grade financial analysis system that:

- Collects real stock prices, news, and sentiment every few minutes automatically
- Runs ML models daily to forecast prices and predict market direction
- Detects unusual price and volume events using statistical analysis
- Scores news article sentiment using transformer-based NLP
- Answers natural language questions about any stock using RAG + LLaMA3
- Displays everything in an interactive web dashboard

Ask it: *"Give me a full analysis of Apple stock"*
It retrieves live prices, forecasts, news, and sentiment — then generates a grounded answer.

## Architecture
Real financial data (yfinance, NewsAPI, RSS, Alpha Vantage)
↓
Kafka event stream (Docker — KRaft mode, no Zookeeper)
↓
ClickHouse (price time-series) + PostgreSQL/RDS (news, forecasts, vectors)
↓
ML Pipeline (automated via Celery):
Prophet          → 7-day price forecast with confidence intervals
XGBoost          → buy/sell direction signal + confidence score
spaCy NER        → extracts ticker mentions from news headlines
sentence-transformers → sentiment scoring -1.0 to +1.0
statsmodels      → z-score anomaly detection (price + volume)
pgvector         → 384-dim semantic embeddings for RAG
↓
RAG + AI Layer:
pgvector search  → finds relevant articles for any query
LangGraph agent  → intent → retrieve → generate workflow
Groq LLaMA3-70b  → generates grounded natural language answers
↓
Streamlit Dashboard (5 pages):
Market Overview  → all stocks watchlist + ML signals
Stock Detail     → price charts, forecasts, sentiment, news
Anomalies        → alert feed with severity filtering
AI Chat          → natural language Q&A with chat history
Settings         → system health + stock management

## Tech Stack

| Layer | Technology |
|---|---|
| API | FastAPI 0.111, Pydantic v2, SQLAlchemy 2.0 |
| Dashboard | Streamlit, Plotly (interactive charts) |
| Primary DB | AWS RDS PostgreSQL 16 + pgvector extension |
| Time-series DB | ClickHouse 23.8 (Docker) |
| Cache / Broker | Redis 7 (Docker) + Celery 5.4 |
| Message Queue | Kafka 7.5 (KRaft mode, Docker) |
| ML Forecasting | Prophet 1.1.5, XGBoost 2.0.3 |
| ML NLP | spaCy 3.7.5, sentence-transformers 2.7.0 |
| ML Stats | statsmodels 0.14.2, scikit-learn 1.4.2 |
| ML Tracking | MLflow 2.13.0 |
| AI Agent | LangGraph 0.1.1, LangChain 0.2.5 |
| LLM | Groq API — LLaMA3-70b (free tier) |
| Vector Search | pgvector cosine similarity |
| Storage | AWS S3 (raw data + MLflow artifacts) |
| Monitoring | AWS CloudWatch, Flower, MLflow UI |
| CI/CD | GitHub Actions → AWS ECR → EC2 (Phase 6) |

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
| Groq API | LLaMA3-70b LLM inference | Yes (free tier) |

## Project Phases

| Phase | What | Status |
|---|---|---|
| Phase 1 | Foundation — FastAPI, AWS RDS, Docker, Alembic, tests | ✅ Complete |
| Phase 2 | Data ingestion — prices, news, sentiment via Kafka | ✅ Complete |
| Phase 3 | ML models — Prophet, XGBoost, NLP, anomaly detection | ✅ Complete |
| Phase 4 | RAG + LangGraph AI agent + Groq LLM chat API | ✅ Complete |
| Phase 5 | Streamlit dashboard — 5 pages, charts, AI chat UI | ✅ Complete |
| Phase 6 | Deploy to AWS EC2 + GitHub Actions CI/CD | 🔄 In progress |

## Getting Started

### Prerequisites
- Docker Desktop
- Python 3.11
- AWS account (free tier)
- Groq API key — free at [console.groq.com](https://console.groq.com)
- NewsAPI key — free at [newsapi.org](https://newsapi.org)

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

# Download spaCy model
python -m spacy download en_core_web_sm

# Run database migrations
alembic upgrade head

# Seed initial stock data
python scripts/seed_stocks.py

# Seed 1 year of historical prices into ClickHouse
python scripts/seed_prices.py

# Start all services (API + dashboard + all pipelines)
docker compose up --build
```

### Open the dashboard
http://localhost:8501

### Verify the API

```bash
curl http://localhost:8000/health
curl http://localhost:8000/api/prices/AAPL
curl -X POST http://localhost:8000/api/chat/ \
  -H "Content-Type: application/json" \
  -d '{"question": "What is the outlook for Apple?"}'
```

### Local monitoring

| URL | What |
|---|---|
| http://localhost:8501 | Streamlit dashboard (5 pages) |
| http://localhost:8000/docs | FastAPI Swagger UI (22 endpoints) |
| http://localhost:5555 | Flower — Celery task monitor |
| http://localhost:5001 | MLflow — ML experiment tracker |
| http://localhost:8090 | Kafka UI — message stream monitor |
| http://localhost:8080 | Adminer — database browser |
| http://localhost:8123/play | ClickHouse SQL playground |

### Run tests

```bash
pytest tests/ -v
```

## Automated Data Pipeline
Every 5 min    yfinance → Kafka → ClickHouse ohlcv
Every 15 min   ClickHouse → z-score → RDS anomalies
Every 30 min   NewsAPI + RSS → Kafka → RDS news_articles
spaCy NER → fills ticker_symbols
sentence-transformers → fills sentiment_score
Every hour     Alpha Vantage → Kafka → RDS sentiment signals
sentence-transformers → pgvector embeddings
Daily 9am UTC  Prophet → 7-day price forecast → RDS
XGBoost → direction signal → RDS

## Dashboard Pages

### Market Overview (Home)
- Live watchlist showing all 10 stocks with current prices
- ML signal badges (UP/DOWN) with confidence percentages
- Mini sparkline charts for 7-day price trend
- Recent anomaly alerts with severity indicators
- System health status for RDS and ClickHouse

### Stock Detail
- Interactive candlestick price chart with volume bars
- 7-day Prophet price forecast with 80% confidence bands
- XGBoost direction signal with model accuracy
- Daily sentiment trend bar chart (bullish/bearish/neutral)
- Latest news feed with sentiment scores and source links
- One-click forecast trigger button

### Anomalies
- Full anomaly alert feed filterable by stock and severity
- Statistical details (z-score, actual vs expected values)
- Table view for easy scanning across all detected events

### AI Chat
- Natural language Q&A powered by LangGraph + Groq LLaMA3
- Persistent chat history within session
- Example question shortcuts in sidebar
- Source transparency (shows which stocks and intent were used)
- Covers: prices, forecasts, news analysis, anomalies, sentiment

### Settings
- Live system health indicators (RDS, ClickHouse)
- Full tracked stocks table with sector/industry
- Quick links to all monitoring dashboards

## API Reference (22 endpoints)

### System
| GET | /health | RDS + ClickHouse health |
| GET | /docs | Swagger UI |

### Stocks (5 endpoints)
| GET/POST/PATCH/DELETE | /api/stocks/* | CRUD operations |

### Prices (4 endpoints)
| GET | /api/prices/ | All stocks latest |
| GET | /api/prices/{symbol} | Latest + change % |
| GET | /api/prices/{symbol}/history | Historical candles |
| GET | /api/prices/{symbol}/summary | Daily aggregates |

### News + Sentiment (3 endpoints)
| GET | /api/news/ | All recent news |
| GET | /api/news/{symbol} | Symbol news |
| GET | /api/news/{symbol}/sentiment | Sentiment series |

### Forecasts (3 endpoints)
| GET | /api/forecasts/ | All signals |
| GET | /api/forecasts/{symbol} | Full forecast |
| POST | /api/forecasts/{symbol}/run | Trigger models |

### Anomalies (2 endpoints)
| GET | /api/anomalies/ | All anomalies |
| GET | /api/anomalies/{symbol} | Symbol anomalies |

### AI Chat (2 endpoints)
| POST | /api/chat/ | Ask a question |
| GET | /api/chat/health | Groq configuration |

## AWS Infrastructure (all free tier)

| Service | Purpose | Free tier |
|---|---|---|
| RDS t3.micro | PostgreSQL 16 + pgvector | 750 hrs/month, 12 months |
| EC2 t2.micro | FastAPI + Celery (Phase 6) | 750 hrs/month, 12 months |
| S3 | Raw data archive + MLflow artifacts | 5 GB forever |
| SES | Alert emails | 3,000/month forever |
| CloudWatch | Structured JSON logs | 5 GB forever |

## Key Technical Decisions

**Why two databases?**
ClickHouse handles millions of 5-minute price candles with sub-second aggregations.
Postgres handles text, relationships, and pgvector for RAG semantic search.
Each database does what it does best.

**Why Kafka?**
Decoupling. Fetchers publish and move on. Consumers process independently.
If ClickHouse restarts, no price data is lost — messages wait in Kafka.

**Why pre-compute ML predictions?**
Prophet takes 30 seconds per symbol. Celery runs this at 9am daily.
The API returns pre-computed results in 30ms. Users never wait.

**Why RAG instead of asking the LLM directly?**
LLMs have knowledge cutoffs. RAG retrieves your actual current data first,
then the LLM generates answers grounded in real prices, news, and forecasts.

**Why Streamlit?**
Pure Python — no HTML, CSS, or JavaScript. The entire dashboard is Python.
Charts, tables, chat interfaces, metrics — all rendered from Python code.
Perfect for a data-heavy application where the backend is already Python.

## What I Built and Learned

**Architecture patterns:**
- Event-driven data pipeline with Kafka decoupling
- Two-database strategy optimised for different query types
- RAG pattern with pgvector semantic retrieval
- LangGraph multi-node agent with intent classification
- Pre-computation pattern for ML predictions (Celery + API separation)

**ML engineering:**
- Time-series forecasting with Prophet (trend + seasonality)
- Binary classification with XGBoost (no-shuffle time-series split)
- Statistical anomaly detection with rolling z-scores
- Zero-shot sentiment scoring with sentence-transformers
- NER with spaCy for ticker entity extraction
- MLflow experiment tracking across Prophet + XGBoost runs

**Infrastructure:**
- AWS free tier: RDS PostgreSQL, S3, CloudWatch
- Docker Compose with 11 services running simultaneously
- Structured JSON logging with CloudWatch integration
- Alembic migrations with version-controlled schema changes

**API and UI design:**
- 22 REST endpoints across 6 domains
- FastAPI dependency injection + global error handling
- Streamlit 5-page dashboard with Plotly interactive charts
- Persistent chat history with session state management

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