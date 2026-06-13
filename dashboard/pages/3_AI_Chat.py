# =========================================================
# AI CHAT PAGE
# =========================================================
#
# Natural language Q&A powered by RAG + Groq LLaMA3.
# Users type questions, the LangGraph agent retrieves
# real data and generates grounded answers.
#
# Connection chain:
# User types question
#       ↓
# POST /api/chat/ (api_client.ask_ai())
#       ↓
# LangGraph agent (Phase 4)
#   → pgvector semantic search
#   → price/forecast/anomaly tools
#   → Groq LLaMA3 generation
#       ↓
# Answer displayed in chat interface

import streamlit as st
from components.api_client import ask_ai, get_health
from components.metrics import health_indicator

st.set_page_config(
    page_title="AI Chat — FinMarket",
    page_icon="🤖",
    layout="wide"
)

with st.sidebar:
    st.title("📈 FinMarket")
    st.divider()
    health = get_health()
    health_indicator(health)
    st.divider()

    st.markdown("**Example questions:**")
    examples = [
        "What is the forecast for Apple?",
        "Any unusual market activity today?",
        "What happened to NVIDIA this week?",
        "Give me a full analysis of Goldman Sachs",
        "Which stocks have bearish signals?",
        "What is the sentiment for Microsoft?"
    ]
    for ex in examples:
        if st.button(ex, use_container_width=True):
            st.session_state.example_question = ex

st.title("🤖 FinMarket AI")
st.caption(
    "Ask anything about the 10 tracked stocks. "
    "Powered by LangGraph + Groq LLaMA3-70b + RAG."
)

# ── Chat history ──────────────────────────────────────────
#
# st.session_state persists data across reruns.
# Without it, chat history would clear on every interaction.
if "messages" not in st.session_state:
    st.session_state.messages = []

# ── Display chat history ──────────────────────────────────
for message in st.session_state.messages:
    with st.chat_message(message["role"]):
        st.markdown(message["content"])

        # Show metadata for AI responses
        if message["role"] == "assistant" and \
           "metadata" in message:
            meta = message["metadata"]
            with st.expander("View sources"):
                if meta.get("symbols"):
                    st.caption(
                        f"**Stocks:** {', '.join(meta['symbols'])}"
                    )
                if meta.get("intent"):
                    st.caption(f"**Intent:** {meta['intent']}")

# ── Handle example question from sidebar ─────────────────
if "example_question" in st.session_state:
    question = st.session_state.pop("example_question")
    st.session_state.messages.append({
        "role": "user",
        "content": question
    })
    with st.chat_message("user"):
        st.markdown(question)

    with st.chat_message("assistant"):
        with st.spinner("Thinking..."):
            result = ask_ai(question)

        if result:
            answer = result.get("answer", "No answer returned.")
            st.markdown(answer)
            st.session_state.messages.append({
                "role": "assistant",
                "content": answer,
                "metadata": {
                    "symbols": result.get("symbols", []),
                    "intent":  result.get("intent", "")
                }
            })
        else:
            error_msg = (
                "Could not get a response. "
                "Make sure the API is running and "
                "GROQ_API_KEY is configured."
            )
            st.error(error_msg)
            st.session_state.messages.append({
                "role": "assistant",
                "content": error_msg
            })

    st.rerun()

# ── Chat input ────────────────────────────────────────────
if question := st.chat_input("Ask about any tracked stock..."):

    # Add user message to history
    st.session_state.messages.append({
        "role": "user",
        "content": question
    })

    with st.chat_message("user"):
        st.markdown(question)

    # Generate AI response
    with st.chat_message("assistant"):
        with st.spinner("Researching..."):
            result = ask_ai(question)

        if result:
            answer = result.get("answer", "No answer returned.")
            st.markdown(answer)

            with st.expander("View sources"):
                symbols = result.get("symbols", [])
                intent  = result.get("intent", "")
                if symbols:
                    st.caption(f"**Stocks:** {', '.join(symbols)}")
                if intent:
                    st.caption(f"**Intent:** {intent}")

            st.session_state.messages.append({
                "role": "assistant",
                "content": answer,
                "metadata": {
                    "symbols": result.get("symbols", []),
                    "intent":  result.get("intent", "")
                }
            })
        else:
            error_msg = (
                "⚠️ Could not reach the AI. "
                "Check that Docker is running and "
                "GROQ_API_KEY is set in .env"
            )
            st.error(error_msg)
            st.session_state.messages.append({
                "role": "assistant",
                "content": error_msg
            })

# ── Clear chat button ─────────────────────────────────────
if st.session_state.messages:
    if st.button("Clear chat history"):
        st.session_state.messages = []
        st.rerun()