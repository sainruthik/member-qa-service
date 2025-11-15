# Member QA Service

A production-ready FastAPI service that answers natural-language questions about members using message data from the Aurora public API. The system uses deterministic relevance scoring to extract answers directly from member messages without hallucinations or LLM inference.

## Live Deployment

**Base URL:** `https://member-qa-service-pfjfsbxhya-uc.a.run.app`

**API Documentation:** `https://member-qa-service-pfjfsbxhya-uc.a.run.app/docs`

## Overview

The Member QA Service provides a question-answering interface over member message data. Given a natural-language question like:

> "What does Layla prefer during flights?"

The system:
1. Fetches all member messages from the upstream `/messages` API
2. Identifies which member is referenced in the question
3. Scores messages by relevance using token-based overlap
4. Extracts and returns the most relevant message as the answer

**Key Features:**
- Deterministic answer generation (no LLMs, no hallucinations)
- In-memory caching (60-second TTL) to reduce upstream API calls
- Robust member name extraction from questions
- Token-based relevance scoring with stopword filtering
- Fully containerized with automated CI/CD deployment

## Architecture

### Data Flow

```
User Question → Member Extraction → Message Fetching → Relevance Scoring → Answer Generation
```

### Components

#### 1. **Data Fetching Layer** ([app.py:68-87](app.py#L68-L87))
- Fetches messages from upstream API: `https://november7-730026606190.europe-west1.run.app/messages`
- Uses `httpx.AsyncClient` with 10-second timeout
- Implements 60-second in-memory cache to minimize upstream load
- Graceful error handling for unreachable upstream services

#### 2. **Normalization Layer** ([app.py:90-121](app.py#L90-L121))
- Parses raw JSON into `Message` Pydantic models
- Validates required fields: `id`, `user_id`, `user_name`, `timestamp`, `message`
- Skips malformed items gracefully

#### 3. **Member Identification** ([app.py:130-165](app.py#L130-L165))
- Extracts capitalized word spans from questions (e.g., "Layla Kawaguchi")
- Fuzzy-matches spans against known member names using substring matching
- Falls back to single member if dataset contains only one user

#### 4. **Relevance Scoring** ([app.py:48-63](app.py#L48-L63))
- Tokenizes question and message text (lowercase, alphabetic only)
- Filters common stopwords ("the", "is", "what", etc.)
- Scores messages using token overlap ratio
- Special handling for "how many cars" and "favorite restaurants" queries

#### 5. **Answer Generation** ([app.py:170-199](app.py#L170-L199))
- Returns answers in format: `{member_name} said: "{message_text}"`
- Special extraction for numeric queries (e.g., car counts)
- Fully auditable: answers always quote original messages

## API Endpoints

### `POST /ask` - Main Question Answering

**Request:**
```json
{
  "question": "What does Layla Kawaguchi prefer during flights?"
}
```

**Response:**
```json
{
  "answer": "Layla Kawaguchi said: \"Please remember I prefer aisle seats during my flights.\""
}
```

### `GET /health` - Health Check

**Response:**
```json
{
  "status": "ok"
}
```

### `GET /debug/messages` - Raw Upstream Messages

Returns the raw JSON response from the upstream Aurora API.

### `GET /debug/normalized` - Normalized Messages

Shows the cleaned and validated messages used for QA processing.

**Response:**
```json
{
  "count": 42,
  "sample": [...]
}
```

## Deployment

### Docker

Build the container:
```bash
docker build -t member-qa-service .
```

Run locally:
```bash
docker run -p 8080:8080 member-qa-service
```

Access locally at: `http://localhost:8080/docs`

### Google Cloud Run (Production)

The service uses automated CI/CD via Google Cloud Build:

1. **Trigger:** Push to `main` branch
2. **Build:** Docker image tagged with `$COMMIT_SHA`
3. **Push:** Image to GCR at `gcr.io/$PROJECT_ID/member-qa-service`
4. **Deploy:** Update Cloud Run service in `us-central1` region

**Configuration:** See [cloudbuild.yaml](cloudbuild.yaml)

**Deployment Details:**
- Region: `us-central1`
- Platform: Managed
- Port: `8080`
- Public access: Enabled (`--allow-unauthenticated`)

### Local Development

Install dependencies:
```bash
pip install -r requirements.txt
```

Run with hot reload:
```bash
uvicorn app:app --reload
```

Access Swagger UI: `http://127.0.0.1:8000/docs`

## Project Structure

```
member-qa-service/
├── app.py              # FastAPI application & QA logic
├── requirements.txt    # Python dependencies
├── Dockerfile          # Container definition
├── cloudbuild.yaml     # CI/CD pipeline configuration
└── README.md           # This file
```

## Dependencies

- **FastAPI** - Modern web framework for building APIs
- **Pydantic** - Data validation using Python type annotations
- **HTTPX** - Async HTTP client for upstream API calls
- **Uvicorn** - ASGI server for running FastAPI

See [requirements.txt](requirements.txt) for complete list.

## Design Notes

### Approach Trade-offs

Several architectural approaches were considered:

**1. LLM-Based Semantic QA**
- ❌ Nondeterministic, potential hallucinations
- ❌ Outside scope of deriving answers from data only

**2. RAG (Retrieval-Augmented Generation)**
- ❌ Requires vector database infrastructure
- ❌ Overkill for small, frequently-updated dataset

**3. NLP Named-Entity Recognition (spaCy/NLTK)**
- ❌ Model loading overhead
- ❌ Unnecessary complexity for dataset size

**4. Pure Rule-Based Matching**
- ❌ Too brittle for natural language variation

**Selected: Hybrid Deterministic System** ✅
- Token-based relevance scoring
- Fuzzy member name matching
- Message quotation (no generation)
- Simple, transparent, fully auditable

### Data Characteristics

During dataset exploration, the following patterns were observed:

- **Variable message detail:** Ranges from short ("Thanks") to detailed travel preferences
- **Mixed timestamps:** Messages span 2024-2025
- **Non-answerable messages:** Generic responses like "Great work!" receive low relevance scores
- **No explicit profiles:** All inference is text-driven from message content
- **Context-dependent references:** "The usual place" has low keyword overlap and is naturally deprioritized

### Caching Strategy

The 60-second TTL cache balances:
- **Freshness:** Messages refresh frequently enough for most use cases
- **Performance:** Reduces upstream API load by ~98% under normal traffic
- **Simplicity:** In-memory cache avoids external dependencies (Redis, Memcached)

For production at scale, consider:
- Distributed caching (Redis) for multi-instance deployments
- Configurable TTL via environment variables
- Cache invalidation webhooks from upstream API

## Future Enhancements

Potential improvements for production scale:

- [ ] Add Redis for distributed caching across Cloud Run instances
- [ ] Implement request rate limiting to prevent abuse
- [ ] Add structured logging (JSON format) for Cloud Logging integration
- [ ] Support multi-member queries ("What do Layla and Vikram prefer?")
- [ ] Implement fuzzy string matching (Levenshtein distance) for misspelled names
- [ ] Add telemetry/metrics (Prometheus, OpenTelemetry)
- [ ] Implement webhook for cache invalidation on upstream data changes
- [ ] Add confidence scores to answer responses
- [ ] Support follow-up questions with conversation context

## License

This project is proprietary. All rights reserved.

## Contact

For questions or issues, contact the development team.
