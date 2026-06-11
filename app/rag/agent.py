# path: app/rag/agent.py

# =========================================================
# LANGGRAPH AI AGENT
# =========================================================
#
# What is this file in plain English?
#
# This is the brain of the AI system. It decides:
# 1. What does the user actually want to know?
# 2. Which data sources are relevant?
# 3. How to combine everything into one answer?
#
# LangGraph builds a graph of nodes (steps).
# Each node is a Python function.
# The agent follows the graph to produce an answer.
#
# Our agent flow:
#
# User question
#       ↓
# Node 1: extract_intent
#   → figures out what symbols and topics are relevant
#   → "What happened to Apple?" → symbol=AAPL, topic=news
#       ↓
# Node 2: retrieve_context
#   → calls the right rag_tools functions
#   → fetches prices, news, forecasts, anomalies
#       ↓
# Node 3: generate_answer
#   → sends context + question to Groq LLM
#   → LLM generates a natural language answer
#       ↓
# Final answer to user
#
# ─────────────────────────────────────────────────────────
# HOW THIS FILE CONNECTS TO OTHER SCRIPTS:
#
# rag_tools.py ── all data retrieval functions
#       ↓
# THIS FILE (agent.py) orchestrates the flow
#       ↓
# Groq API (free LLaMA3) generates text
#       ↓
# api/chat.py → POST /api/chat
#       ↓
# User receives intelligent answer
# ─────────────────────────────────────────────────────────

import re
from typing import TypedDict, Annotated
from langgraph.graph import StateGraph, END
from langchain_groq import ChatGroq
from langchain_core.messages import HumanMessage, SystemMessage

from app.rag.rag_tools import (
    search_news,
    get_price_data,
    get_forecast_data,
    get_anomaly_data,
    get_sentiment_summary
)
from app.config import settings
from app.utils.logger import get_logger

logger = get_logger(__name__)

# ── Tracked symbols for intent extraction ────────────────
TRACKED_SYMBOLS = [
    "AAPL", "MSFT", "GOOGL", "NVDA", "META",
    "JPM", "GS", "JNJ", "XOM", "AMZN"
]

# ── Company name → symbol mapping ────────────────────────
COMPANY_MAP = {
    "apple": "AAPL", "microsoft": "MSFT",
    "google": "GOOGL", "alphabet": "GOOGL",
    "nvidia": "NVDA", "meta": "META",
    "facebook": "META", "jpmorgan": "JPM",
    "goldman": "GS", "johnson": "JNJ",
    "exxon": "XOM", "amazon": "AMZN"
}


# ── Agent State ───────────────────────────────────────────
#
# TypedDict defines what information flows between nodes.
# Each node reads from state and adds to state.
# LangGraph passes state between nodes automatically.
class AgentState(TypedDict):
    question:       str           # original user question
    symbols:        list[str]     # extracted ticker symbols
    intent:         str           # news/price/forecast/general
    context:        str           # retrieved data as text
    answer:         str           # final LLM response
    error:          str           # error message if any


# ── Node 1: Extract Intent ────────────────────────────────

def extract_intent(state: AgentState) -> AgentState:
    """
    Figures out what the user is asking and which stocks.

    Extracts:
    - symbols: which tickers are relevant (AAPL, MSFT etc.)
    - intent:  what type of data to retrieve
               news / price / forecast / anomaly / general

    No LLM call needed here — simple pattern matching
    is faster and uses no API quota.

    Example:
    "Should I buy Apple given recent news?"
    → symbols: ["AAPL"]
    → intent: "general" (asks for multiple data types)
    """
    question = state["question"].upper()
    question_lower = state["question"].lower()

    # ── Extract symbols ───────────────────────────────────
    found_symbols = []

    # Check for direct ticker mentions ($AAPL or AAPL)
    for symbol in TRACKED_SYMBOLS:
        if symbol in question or f"${symbol}" in question:
            found_symbols.append(symbol)

    # Check for company name mentions
    if not found_symbols:
        for company, symbol in COMPANY_MAP.items():
            if company in question_lower:
                if symbol not in found_symbols:
                    found_symbols.append(symbol)

    # Default to general market if no specific symbol
    if not found_symbols:
        found_symbols = []

    # ── Classify intent ───────────────────────────────────
    #
    # Simple keyword matching to classify what data to fetch
    if any(w in question_lower for w in
       ["anomaly", "unusual", "spike", "crash",
        "alert", "warning", "strange", "activity",
        "weird", "odd", "unexpected"]):
        intent = "anomaly"

    elif any(w in question_lower for w in
            ["forecast", "predict", "tomorrow", "next week",
            "signal", "buy", "sell", "up or down", "prediction"]):
        intent = "forecast"

    elif any(w in question_lower for w in
            ["news", "happened", "why", "announced",
            "said", "reported", "article", "headlines"]):
        intent = "news"

    elif any(w in question_lower for w in
            ["sentiment", "feeling", "bullish", "bearish",
            "opinion", "mood"]):
        intent = "sentiment"

    elif any(w in question_lower for w in
            ["price", "trading", "worth", "cost",
            "high", "low", "volume", "current"]):
        # Removed "today" from price keywords
        # "today" alone should not force price intent
        intent = "price"

    else:
        intent = "general"

    logger.info(
        "intent_extracted",
        extra={
            "question": state["question"][:50],
            "symbols":  found_symbols,
            "intent":   intent
        }
    )

    return {
        **state,
        "symbols": found_symbols,
        "intent":  intent
    }


# ── Node 2: Retrieve Context ──────────────────────────────

def retrieve_context(state: AgentState) -> AgentState:
    """
    Fetches relevant data based on intent and symbols.

    Calls the appropriate rag_tools functions and
    combines their outputs into one context string
    that the LLM will use to answer the question.

    This is the RETRIEVAL step of RAG.

    Connection:
    state.intent + state.symbols
        ↓
    calls rag_tools.py functions
        ↓
    combines into one context string
        ↓
    state.context → used by generate_answer node
    """
    intent  = state["intent"]
    symbols = state["symbols"]
    question = state["question"]

    context_parts = []

    # ── Always search news semantically ──────────────────
    #
    # vector_store.search_similar_articles() finds articles
    # most relevant to the question regardless of intent
    primary_symbol = symbols[0] if symbols else None
    news_context   = search_news(question, primary_symbol)

    if news_context and news_context != "No relevant news articles found.":
        context_parts.append(
            f"=== RELEVANT NEWS ===\n{news_context}"
        )

    # ── Add data based on intent ──────────────────────────
    for symbol in symbols[:2]:

        # Price intent also includes forecast for completeness
        if intent in ("price", "forecast", "general"):
            price_ctx = get_price_data(symbol)
            context_parts.append(
                f"=== PRICE DATA: {symbol} ===\n{price_ctx}"
            )

        # Forecast intent also includes price for context
        if intent in ("price", "forecast", "general"):
            forecast_ctx = get_forecast_data(symbol)
            context_parts.append(
                f"=== FORECAST: {symbol} ===\n{forecast_ctx}"
            )

        if intent in ("anomaly", "general"):
            anomaly_ctx = get_anomaly_data(symbol)
            if "No anomalies" not in anomaly_ctx:
                context_parts.append(
                    f"=== ANOMALIES: {symbol} ===\n{anomaly_ctx}"
                )

        if intent in ("sentiment", "general"):
            sentiment_ctx = get_sentiment_summary(symbol)
            context_parts.append(
                f"=== SENTIMENT: {symbol} ===\n{sentiment_ctx}"
            )

    # ── Handle general market questions ──────────────────
    if not symbols:
        anomaly_ctx = get_anomaly_data()
        if "No anomalies" not in anomaly_ctx:
            context_parts.append(
                f"=== MARKET ANOMALIES ===\n{anomaly_ctx}"
            )

    context = "\n\n".join(context_parts)

    if not context:
        context = (
            "No specific data found. "
            "I can help with questions about: "
            + ", ".join(TRACKED_SYMBOLS)
        )

    logger.info(
        "context_retrieved",
        extra={
            "intent":       intent,
            "symbols":      symbols,
            "context_len":  len(context)
        }
    )

    return {**state, "context": context}


# ── Node 3: Generate Answer ───────────────────────────────

def generate_answer(state: AgentState) -> AgentState:
    """
    Calls Groq LLM to generate final answer.

    Sends:
    - System prompt: who the AI is + data format
    - Context: all the retrieved financial data
    - Question: the user's original question

    Groq uses LLaMA3 to generate a natural language
    answer grounded in your real data.

    This is the GENERATION step of RAG.

    Connection:
    state.context (from retrieve_context)
    state.question (original)
        ↓
    Groq API (free LLaMA3-70b)
        ↓
    state.answer → returned to user via api/chat.py
    """
    try:
        # ── Initialise Groq LLM ───────────────────────────
        #
        # ChatGroq wraps the Groq API.
        # model: llama3-70b-8192 = best quality, still fast
        # temperature: 0.1 = mostly deterministic
        #              (lower = more factual, less creative)
        llm = ChatGroq(
            api_key=settings.groq_api_key,
            model="llama-3.3-70b-versatile",
            temperature=0.1,
            max_tokens=1024
        )

        # ── System prompt ─────────────────────────────────
        #
        # Tells the LLM its role and how to use the context.
        # Explicitly forbids hallucination.
        system_prompt = """You are FinMarket AI, an intelligent
financial analysis assistant. You have access to real-time
financial data including stock prices, news articles,
ML forecasts, sentiment analysis, and anomaly detection.

Use ONLY the data provided in the context below to answer
questions. Do not make up prices, forecasts, or news.
If the context does not contain enough information,
say so clearly.

Be concise, factual, and helpful. Format numbers clearly.
When discussing forecasts, always mention that these are
model predictions, not financial advice."""

        # ── Build messages ────────────────────────────────
        messages = [
            SystemMessage(content=system_prompt),
            HumanMessage(content=(
                f"Context data:\n{state['context']}\n\n"
                f"Question: {state['question']}"
            ))
        ]

        # ── Call Groq API ─────────────────────────────────
        response = llm.invoke(messages)
        answer   = response.content

        logger.info(
            "answer_generated",
            extra={
                "question": state["question"][:50],
                "answer_len": len(answer)
            }
        )

        return {**state, "answer": answer}

    except Exception as e:
        logger.error(f"generate_answer_error: {e}")
        return {
            **state,
            "answer": (
                "I encountered an error generating a response. "
                f"Error: {str(e)}"
            )
        }


# ── Build LangGraph workflow ──────────────────────────────

def build_agent():
    """
    Assembles the LangGraph agent graph.

    Graph structure:
    START → extract_intent → retrieve_context → generate_answer → END

    Each arrow = one node's output becomes next node's input.
    LangGraph passes the AgentState dict between nodes.
    """

    # ── Create the graph ──────────────────────────────────
    #
    # StateGraph takes our AgentState TypedDict.
    # It knows what fields to pass between nodes.
    workflow = StateGraph(AgentState)

    # ── Add nodes ─────────────────────────────────────────
    workflow.add_node("extract_intent",   extract_intent)
    workflow.add_node("retrieve_context", retrieve_context)
    workflow.add_node("generate_answer",  generate_answer)

    # ── Define edges (flow between nodes) ─────────────────
    #
    # set_entry_point = where to start
    # add_edge = A always goes to B
    # set_finish_point = where to end
    workflow.set_entry_point("extract_intent")
    workflow.add_edge("extract_intent",   "retrieve_context")
    workflow.add_edge("retrieve_context", "generate_answer")
    workflow.add_edge("generate_answer",  END)

    # ── Compile the graph ─────────────────────────────────
    #
    # compile() validates the graph and returns
    # a runnable object you can call with .invoke()
    return workflow.compile()


# ── Create agent instance ─────────────────────────────────
#
# Built once at module level.
# api/chat.py imports and uses this instance.
agent = build_agent()


def run_agent(question: str) -> dict:
    """
    Main entry point — runs the full agent pipeline.

    Takes a user question, runs through all nodes,
    returns the final answer with metadata.

    Called by api/chat.py POST /api/chat endpoint.
    """
    if not settings.groq_api_key:
        return {
            "answer":  "Groq API key not configured.",
            "symbols": [],
            "intent":  "error",
            "context": ""
        }

    # ── Run the graph ─────────────────────────────────────
    #
    # .invoke() starts at entry_point (extract_intent)
    # and runs through all nodes until END.
    # Returns the final AgentState dict.
    result = agent.invoke({
        "question": question,
        "symbols":  [],
        "intent":   "",
        "context":  "",
        "answer":   "",
        "error":    ""
    })

    return {
        "answer":  result["answer"],
        "symbols": result["symbols"],
        "intent":  result["intent"],
        "context": result["context"][:500] + "..."
        if len(result.get("context", "")) > 500
        else result.get("context", "")
    }