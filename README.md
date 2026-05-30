# FinMarket-Intelligence-Platform
A platform that ingests stock/economic data, runs forecasting models, answers natural language questions about markets, and sends alerts.

# FinMarket Intelligence Platform

A full-stack financial intelligence platform with real-time data pipelines,
ML forecasting, RAG-powered AI analysis, and automated alerting.
Built entirely on free infrastructure.

![Python](https://img.shields.io/badge/Python-3.11-blue)
![FastAPI](https://img.shields.io/badge/FastAPI-0.111-green)
![AWS](https://img.shields.io/badge/AWS-RDS%20%7C%20S3%20%7C%20ElastiCache-orange)
![Docker](https://img.shields.io/badge/Docker-Compose-blue)

## Live Demo
> Dashboard: [coming in Phase 5]
> API Docs: [coming in Phase 6]

## Architecture

Real financial data (yfinance, NewsAPI, Reddit)
↓
Kafka event stream (Upstash — free)
↓
ClickHouse (time-series) + PostgreSQL/RDS (relational)
↓
ML models (Prophet forecasting, XGBoost signals,
spaCy NER, sentence-transformers sentiment)
↓
RAG layer (pgvector semantic search + LangGraph agent
+ Groq LLaMA3 — free cloud LLM)
↓
Streamlit dashboard + REST API (FastAPI on AWS EC2)

## Tech Stack

| Layer | Technology |
|---|---|
| API | FastAPI, Pydantic v2, SQLAlchemy |
| Database | AWS RDS PostgreSQL 16 + pgvector |
| Cache / Queue | AWS ElastiCache Redis + Celery |
| Stream | Kafka (Upstash free tier) |
| Time-series | ClickHouse Cloud (free tier) |
| ML | Prophet, XGBoost, spaCy, sentence-transformers |
| AI | LangGraph, Groq API (LLaMA3), RAG |
| Storage | AWS S3 |
| Monitoring | AWS CloudWatch, Grafana Cloud |
| CI/CD | GitHub Actions → AWS ECR → EC2 |
| Dashboard | Streamlit Community Cloud |

## Project Phases

| Phase | What | Status |
|---|---|---|
| Phase 1 | Foundation, API, AWS setup | ✅ Complete |
| Phase 2 | Data ingestion pipeline | 🔄 In progress |
| Phase 3 | ML models | ⏳ Upcoming |
| Phase 4 | RAG + LangGraph AI layer | ⏳ Upcoming |
| Phase 5 | Dashboard + alerts | ⏳ Upcoming |
| Phase 6 | Deploy + monitor | ⏳ Upcoming |

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
# Edit .env with your AWS RDS and credentials

# Create virtual environment
python3.11 -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\Activate.ps1

# Install dependencies
pip install -r requirements.txt

# Run database migrations
alembic upgrade head

# Seed initial stock data
python scripts/seed_stocks.py

# Start the application
docker compose up --build
```

### Verify it works
```bash
curl http://localhost:8000/health
# {"status": "ok", "database": "connected"}

curl http://localhost:8000/api/stocks/
# {"stocks": [...], "total": 10}
```

### Run tests
```bash
pytest tests/ -v
```

## AWS Infrastructure (all free tier)

| Service | Purpose | Cost |
|---|---|---|
| RDS t3.micro | PostgreSQL + pgvector | Free 12 months |
| ElastiCache | Redis (Celery broker) | Free 12 months |
| EC2 t2.micro | FastAPI + Celery | Free 12 months |
| S3 | Data archive + ML models | 5GB free forever |
| SES | Alert emails | 3000/month free |
| CloudWatch | Logs + metrics | 5GB free forever |

## API Endpoints

| Method | Endpoint | Description |
|---|---|---|
| GET | /health | System health check |
| GET | /api/stocks/ | List all tracked stocks |
| GET | /api/stocks/{symbol} | Get stock by symbol |
| POST | /api/stocks/ | Add new stock |
| PATCH | /api/stocks/{symbol} | Update stock details |
| DELETE | /api/stocks/{symbol} | Deactivate stock |

## What I learned
- Designing a production FastAPI app with proper separation of concerns
- AWS infrastructure setup entirely within free tier
- SQLAlchemy ORM patterns, Alembic migrations, pgvector
- Global error handling and structured JSON logging
- Docker Compose for local development with cloud databases
- Writing pytest test suites for REST APIs

## Author
Palash Aggarwal