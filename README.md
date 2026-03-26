# OmniQueryBot

OmniQueryBot is a lightweight hybrid GenAI Telegram bot built for the assignment brief below:

- `/ask <query>` answers from a local retrieval-augmented knowledge base
- `/image` accepts an uploaded image and returns:
  - one short caption
  - three tags
- `/help` shows usage instructions

This implementation follows the `Hybrid Bot` variant from the assignment: it supports both the Mini-RAG flow and the image-description flow in a single Telegram bot.

For the deeper design explanation, read [ARCHITECTURE.md](d:/OmniQueryBot/ARCHITECTURE.md).

## Assignment Fit

This project satisfies the assignment requirements as follows:

- Bot interface: `Telegram` via `python-telegram-bot`
- Text flow: `Option A - Mini-RAG`
- Image flow: `Option B - Image Description`
- Optional enhancements implemented:
  - last-message awareness with a rewrite/router step
  - per-query embedding cache
  - source snippets shown in RAG answers
  - shared local testing backend

## Features

- Telegram commands:
  - `/help`
  - `/ask`
  - `/image`
- Local knowledge base in `data/knowledge_base`
- Dense retrieval over chunked Markdown docs
- SQLite storage for:
  - indexed documents
  - chunks
  - query cache
  - turn history
  - user state
- Image captioning with structured output
- Provider abstraction for:
  - `Ollama`
  - `Gemini`
- Optional Docker Compose run path

## Current Project Variant

This repo is best described as a `Hybrid Telegram Bot`.

- Text path:
  - retrieves top-k chunks from the local knowledge base
  - builds a grounded prompt
  - generates a concise final answer
- Image path:
  - accepts a Telegram photo or image document
  - normalizes the image
  - generates a caption and exactly 3 tags

## Tech Stack

- Bot framework: `python-telegram-bot`
- Core orchestration: `LangChain`
- Retrieval embeddings: `sentence-transformers/all-MiniLM-L6-v2`
- Vector storage: local `SQLite`
- Text provider options:
  - `Ollama`
  - `Gemini`
- Vision provider options:
  - `Ollama`
  - `Gemini`
- Optional local API/tester backend: `FastAPI`

## Requirements

You need:

- Python `3.11`
- a Telegram bot token
- one of:
  - a running local Ollama server, or
  - a Gemini API key

Optional:

- Docker Desktop for `docker compose`

## Knowledge Base

The current knowledge base intentionally uses exactly 4 large Markdown files:

- `python_virtual_envs.md`
- `fastapi_local_testing.md`
- `docker_basics.md`
- `telegram_bot_operations.md`

Each file contains about `100` FAQ entries, so the indexed knowledge base contains about `400` structured question-answer sections in total.

## Local Setup

### 1. Create and activate the environment

```powershell
uv venv --python 3.11
.\.venv\Scripts\activate
uv pip install -r requirements.txt
```

If you prefer plain pip:

```powershell
python -m venv .venv
.\.venv\Scripts\activate
pip install -e .[dev]
```

### 2. Create `.env`

Create a local `.env` file in the repo root.

### 3. Choose your provider configuration

#### Gemini-backed config

```env
TELEGRAM_BOT_TOKEN=your-telegram-bot-token
GEMINI_API_KEY=your-gemini-api-key

TEXT_PROVIDER=gemini
VISION_PROVIDER=gemini

TEXT_MODEL=gemini-2.5-flash
VISION_MODEL=qwen3:4b
GEMINI_MODEL=gemini-2.5-flash

OLLAMA_BASE_URL=http://localhost:11434
EMBEDDING_MODEL=sentence-transformers/all-MiniLM-L6-v2

DB_PATH=data/omniquerybot.db
KB_DIR=data/knowledge_base

TOP_K=3
HISTORY_WINDOW=3
MIN_RELEVANCE_SCORE=0.32
CHUNK_SIZE=700
CHUNK_OVERLAP=100
SOURCE_SNIPPET_COUNT=2
SOURCE_SNIPPET_LENGTH=180
RAG_MAX_OUTPUT_TOKENS=1024
IMAGE_MAX_EDGE=1600
LOG_LEVEL=INFO
```

#### Ollama-backed config

```env
TELEGRAM_BOT_TOKEN=your-telegram-bot-token

TEXT_PROVIDER=ollama
VISION_PROVIDER=ollama

TEXT_MODEL=qwen3:4b
VISION_MODEL=qwen3:4b

OLLAMA_BASE_URL=http://localhost:11434
EMBEDDING_MODEL=sentence-transformers/all-MiniLM-L6-v2

DB_PATH=data/omniquerybot.db
KB_DIR=data/knowledge_base

TOP_K=3
HISTORY_WINDOW=3
MIN_RELEVANCE_SCORE=0.32
CHUNK_SIZE=700
CHUNK_OVERLAP=100
SOURCE_SNIPPET_COUNT=2
SOURCE_SNIPPET_LENGTH=180
RAG_MAX_OUTPUT_TOKENS=1024
IMAGE_MAX_EDGE=1600
LOG_LEVEL=INFO
```

### 4. Reindex the knowledge base

```powershell
python scripts\reindex.py
```

### 5. Run the Telegram bot

```powershell
python app.py
```

## Docker Compose

You can also run the bot with Docker Compose:

```powershell
docker compose up --build
```

Stop it with:

```powershell
docker compose down
```

## Bot Commands

- `/help`
  - shows usage instructions
- `/ask <query>`
  - answers from the local knowledge base
- `/ask`
  - starts a two-step question flow
- `/image`
  - waits for an uploaded image and returns one caption plus three tags

## How the Bot Behaves

### `/ask`

1. Load the last few turns for that user.
2. Optionally rewrite the latest message into a standalone question.
3. Retrieve top-k chunks from SQLite-backed document chunks.
4. Build a grounded prompt from those sources only.
5. Generate the final answer.
6. Return source file paths and headings.

### `/image`

1. Set the user into image-wait mode.
2. Accept a Telegram image upload.
3. Normalize the image.
4. Generate:
   - one short caption
   - three tags
5. Store the result in turn history.

## Models and APIs Used

### Retrieval

- Embeddings: `sentence-transformers/all-MiniLM-L6-v2`
- Store: local `SQLite`

### Text Generation

- Supported:
  - `Ollama` via `ChatOllama`
  - `Gemini` via the Google GenAI SDK path

### Vision Generation

- Supported:
  - `Ollama` via `ChatOllama`
  - `Gemini` via `ChatGoogleGenerativeAI`

## Why These Choices

Short version:

- `SQLite` keeps the project lightweight and local
- `all-MiniLM-L6-v2` keeps embeddings fast and small
- `LangChain` simplifies provider switching and structured output
- `Gemini` is currently the fastest/stablest path for image description in this repo
- `Ollama` support is still kept for local-first operation

The full reasoning, benefits, and tradeoffs are documented in [ARCHITECTURE.md](d:/OmniQueryBot/ARCHITECTURE.md).

## Testing

Run the test suite with:

```powershell
python -m pytest
```

## Suggested Demo Flow

Use this quick demo sequence:

1. Start the bot with `python app.py`
2. In Telegram, send `/help`
3. Send `/ask How do I create the environment on Windows?`
4. Verify that the reply includes source file paths
5. Send `/image`
6. Upload an image
7. Verify that the reply includes:
   - one caption
   - exactly three tags

## Repository Structure

```text
.
|- app.py
|- web_app.py
|- docker-compose.yml
|- Dockerfile
|- pyproject.toml
|- requirements.txt
|- data/
|  |- omniquerybot.db
|  `- knowledge_base/
|     |- python_virtual_envs.md
|     |- fastapi_local_testing.md
|     |- docker_basics.md
|     `- telegram_bot_operations.md
|- scripts/
|  `- reindex.py
|- src/
|  `- omniquery_bot/
|     |- bot.py
|     |- config.py
|     |- knowledge_base.py
|     |- llm_service.py
|     |- rag_service.py
|     |- vision_service.py
|     `- web_app.py
`- tests/
```

## Deliverables Mapping

The assignment asks for:

- source code
  - included in this repo
- README
  - this file
- system design explanation
  - [ARCHITECTURE.md](d:/OmniQueryBot/ARCHITECTURE.md)
- run instructions
  - included above

## Notes

- Telegram is the primary assignment-facing interface.
- The project supports both RAG and image description, so it fits the `Hybrid Bot` variant.
- The local FastAPI path remains useful for debugging, but the required deliverable is the Telegram bot flow.
