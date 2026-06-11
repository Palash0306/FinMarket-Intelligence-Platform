# path: app/api/chat.py

# =========================================================
# CHAT API — AI Question Answering Endpoint
# =========================================================
#
# This is the front door to the RAG AI agent.
#
# Connection chain:
# User sends POST /api/chat with a question
#       ↓
# THIS FILE validates the request (ChatRequest schema)
#       ↓
# agent.run_agent(question) — LangGraph workflow
#       ↓
# extract_intent → retrieve_context → generate_answer
#       ↓
# ChatResponse returned to user

from fastapi import APIRouter, HTTPException, status
from app.schemas.chat import ChatRequest, ChatResponse
from app.utils.logger import get_logger

logger = get_logger(__name__)

router = APIRouter(
    prefix="/api/chat",
    tags=["AI Chat"]
)


@router.post(
    "/",
    response_model=ChatResponse,
    summary="Ask the AI agent a financial question"
)
def chat(request: ChatRequest):
    """
    Main AI chat endpoint.

    Accepts a natural language question and returns
    an intelligent answer using RAG + Groq LLaMA3.

    Example questions:
    - "What happened to Apple this week?"
    - "Should I be concerned about NVDA's price action?"
    - "What is the forecast for Goldman Sachs?"
    - "Are there any unusual market moves today?"

    The agent:
    1. Identifies relevant stocks and intent
    2. Retrieves relevant news (pgvector search)
    3. Fetches prices, forecasts, anomalies from DB
    4. Generates answer with Groq LLaMA3
    """

    # Lazy import to avoid slow startup
    from app.rag.agent import run_agent

    logger.info(
        "chat_request",
        extra={"question": request.question[:100]}
    )

    try:
        result = run_agent(request.question)

        return ChatResponse(
            answer  = result["answer"],
            symbols = result["symbols"],
            intent  = result["intent"],
            context = result.get("context")
        )

    except Exception as e:
        logger.error(
            "chat_error",
            extra={"error": str(e)}
        )
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"AI agent error: {str(e)}"
        )


@router.get(
    "/health",
    summary="Check if AI agent is configured"
)
def chat_health():
    """Checks if Groq API key is configured."""
    from app.config import settings

    return {
        "groq_configured": bool(settings.groq_api_key),
        "model":           "llama-3.3-70b-versatile",
        "status":          "ready" if settings.groq_api_key
                           else "groq_api_key_missing"
    }