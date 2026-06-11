from pydantic import BaseModel, Field
from typing import Optional


class ChatRequest(BaseModel):
    """What the user sends."""
    question: str = Field(
        min_length=3,
        max_length=500,
        description="Question about stocks or market"
    )
    # Optional: filter context to one symbol
    symbol: Optional[str] = None


class ChatResponse(BaseModel):
    """What the API returns."""
    answer:   str
    symbols:  list[str]
    intent:   str
    # Snippet of retrieved context (for transparency)
    context:  Optional[str] = None