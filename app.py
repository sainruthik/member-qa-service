from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from typing import List, Optional
import httpx
import re
from collections import Counter
import time

app = FastAPI(title="Member QA Service")

# Upstream messages API
MESSAGES_API_URL = "https://november7-730026606190.europe-west1.run.app/messages"

# Simple in-memory cache so we don't hammer the upstream API every time
MESSAGES_CACHE_TTL_SECONDS = 60  # refresh every 60 seconds
_messages_cache: dict = {"timestamp": 0.0, "data": []}


# ---------- Pydantic models ----------

class AskRequest(BaseModel):
    question: str


class AskResponse(BaseModel):
    answer: str


class Message(BaseModel):
    id: str
    user_id: str
    user_name: str
    timestamp: str
    message: str


# ---------- Helper: tokenization & relevance scoring ----------

STOPWORDS = {
    "the", "is", "a", "an", "of", "and", "or", "to", "in", "on",
    "when", "what", "how", "many", "does", "do", "did", "have",
    "has", "for", "are", "about", "tell", "me", "his", "her",
    "their", "who", "where", "which", "that", "this",
}


def tokenize(text: str) -> List[str]:
    words = re.findall(r"[A-Za-z]+", text.lower())
    return [w for w in words if w not in STOPWORDS]


def score_relevance(question: str, message_text: str) -> float:
    q_tokens = tokenize(question)
    m_tokens = tokenize(message_text)
    if not q_tokens or not m_tokens:
        return 0.0
    q_counts = Counter(q_tokens)
    m_counts = Counter(m_tokens)
    overlap = sum(
        min(q_counts[w], m_counts[w]) for w in q_counts.keys() & m_counts.keys()
    )
    return overlap / (len(q_tokens) + 1e-6)


# ---------- Upstream fetch & normalization ----------

async def fetch_messages_from_upstream() -> dict:
    """
    Call the external /messages API and return its JSON.
    """
    try:
        async with httpx.AsyncClient(
            timeout=10.0, follow_redirects=True
        ) as client:
            resp = await client.get(MESSAGES_API_URL)
        if resp.status_code != 200:
            raise HTTPException(
                status_code=502,
                detail=f"Upstream /messages API returned {resp.status_code}",
            )
        return resp.json()
    except httpx.RequestError as e:
        raise HTTPException(
            status_code=502,
            detail=f"Error calling upstream /messages API: {e}",
        )


async def get_all_messages() -> List[Message]:
    """
    Fetch all messages (with simple caching) and normalize into Message objects.
    """
    now = time.time()
    if (
        _messages_cache["data"]
        and now - _messages_cache["timestamp"] < MESSAGES_CACHE_TTL_SECONDS
    ):
        return _messages_cache["data"]

    data = await fetch_messages_from_upstream()
    items = data.get("items", [])
    messages: List[Message] = []

    for item in items:
        try:
            msg = Message(
                id=item["id"],
                user_id=item["user_id"],
                user_name=item["user_name"],
                timestamp=item["timestamp"],
                message=item["message"],
            )
            messages.append(msg)
        except KeyError:
            # Skip malformed items
            continue

    _messages_cache["data"] = messages
    _messages_cache["timestamp"] = now
    return messages


# ---------- Member name extraction ----------

def get_known_user_names(messages: List[Message]) -> List[str]:
    return sorted({m.user_name for m in messages})


def extract_member_name(question: str, known_users: List[str]) -> Optional[str]:
    """
    Naive member name extraction:
    - Find capitalized spans in the question (e.g. 'Layla Kawaguchi', 'Vikram Desai').
    - Match them fuzzily against known user_name values.
    """
    tokens = question.split()
    spans = []
    current = []

    for t in tokens:
        stripped = t.strip(".,?!")
        if stripped and stripped[0].isupper():
            current.append(stripped)
        else:
            if current:
                spans.append(" ".join(current))
                current = []
    if current:
        spans.append(" ".join(current))

    known_lower = [u.lower() for u in known_users]

    for span in spans:
        s = span.lower()
        candidates = [u for u in known_lower if s in u or u in s]
        if candidates:
            # Return original-cased version
            idx = known_lower.index(candidates[0])
            return known_users[idx]

    # If we only have one member in the whole dataset, we can fall back to that
    if len(known_users) == 1:
        return known_users[0]

    return None


# ---------- Answer generation ----------

def generate_answer(question: str, member_name: str, member_messages: List[Message]) -> str:
    if not member_messages:
        return f"I couldn’t find any messages for {member_name} that answer that question."

    sorted_msgs = sorted(
        member_messages,
        key=lambda m: score_relevance(question, m.message),
        reverse=True,
    )
    best = sorted_msgs[0]

    q_lower = question.lower()

    if "how many" in q_lower and "car" in q_lower:
        for m in sorted_msgs[:5]:
            text = m.message.lower()
            digit_match = re.search(r"(\d+)\s+cars?", text)
            if digit_match:
                num = digit_match.group(1)
                return f"{member_name} has {num} car(s)."

        return f"{member_name} said: \"{best.message}\""

    if "favorite restaurants" in q_lower or "favourite restaurants" in q_lower:
        return f"{member_name} said: \"{best.message}\""

    if "trip" in q_lower:
        return f"{member_name} said: \"{best.message}\""

    return f"{member_name} said: \"{best.message}\""


# ---------- Endpoints ----------

@app.get("/health")
def health_check():
    return {"status": "ok"}


@app.get("/debug/messages")
async def debug_messages():
    """
    Raw upstream data.
    """
    data = await fetch_messages_from_upstream()
    return data


@app.get("/debug/normalized")
async def debug_normalized():
    """
    Normalized messages using our Message model.
    """
    messages = await get_all_messages()
    return {
        "count": len(messages),
        "sample": messages[:10],
    }


@app.post("/ask", response_model=AskResponse)
async def ask(req: AskRequest):
    """
    Main QA endpoint:
    1) Fetch & normalize all messages
    2) Detect which member the question is about
    3) Find that member's most relevant messages
    4) Return a short answer based on those messages
    """
    question = req.question

    messages = await get_all_messages()
    if not messages:
        return AskResponse(answer="I couldn’t load any member messages.")

    known_users = get_known_user_names(messages)
    member_name = extract_member_name(question, known_users)

    if not member_name:
        return AskResponse(
            answer="I’m not sure which member you’re asking about based on that question."
        )

    member_messages = [m for m in messages if m.user_name == member_name]

    if not member_messages:
        return AskResponse(
            answer=f"I couldn’t find any messages for {member_name}."
        )

    answer_text = generate_answer(question, member_name, member_messages)
    return AskResponse(answer=answer_text)
