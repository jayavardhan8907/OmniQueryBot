# OmniQueryBot

OmniQueryBot is a lightweight GenAI assignment project with:

- `/ask <query>` for Mini-RAG over a local Markdown knowledge base
- `/image` for image captioning plus 3 tags
- `/summarize` for a short summary of the latest bot interaction
- A local web chat app for testing the same flows in a cleaner browser UI

The codebase is intentionally kept small and easy to explain.

## What It Uses

- Telegram bot: `python-telegram-bot`
- Local embeddings: `sentence-transformers/all-MiniLM-L6-v2`
- Storage: SQLite
- Generation and vision: Gemini `gemini-2.5-flash`
- Image preprocessing: Pillow

## Simple Architecture

```text
Telegram bot or local web chat
            |
            v
       bot.py / web_app.py
            |
            +-- knowledge_base.py  -> chunk docs, embed locally, search SQLite, store history
            |
            `-- genai_client.py    -> Gemini answer generation, image captioning, summaries
```

## Project Structure

```text
.
|- app.py
|- web_app.py
|- web/
|  |- app.js
|  |- index.html
|  `- styles.css
|- data/
|  `- knowledge_base/
|- scripts/
|  `- reindex.py
|- src/
|  `- omniquery_bot/
|     |- bot.py
|     |- config.py
|     |- genai_client.py
|     |- knowledge_base.py
|     `- web_app.py
|- tests/
|- Dockerfile
|- docker-compose.yml
`- pyproject.toml
```

## Why This Is Simpler

- No repository/service/handler/model split
- One file for Telegram bot behavior
- One file for the local knowledge base and SQLite logic
- One file for Gemini calls
- Same features, less code jumping

## Sample Knowledge Base

The repo ships with 4 demo documents:

- `python_virtual_envs.md`
- `git_workflow.md`
- `docker_basics.md`
- `api_debugging.md`

## Local Setup

### 1. Create the environment

Using `uv`:

```powershell
uv venv --python 3.11
.\.venv\Scripts\activate
uv sync --python 3.11 --extra dev
```

Using plain `pip`:

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\activate
pip install --upgrade pip
pip install -e .[dev]
```

### 2. Add your environment variables

Copy `.env.example` to `.env` and fill in:

```env
TELEGRAM_BOT_TOKEN=...
GEMINI_API_KEY=...
```

The rest of the settings already have sensible defaults.

### 3. Build the index

```powershell
.\.venv\Scripts\python scripts\reindex.py
```

The first run downloads the embedding model.

### 4. Start the local web chat app

```powershell
.\.venv\Scripts\python web_app.py
```

Open `http://127.0.0.1:8000` in your browser.

### 5. Start the Telegram bot

```powershell
.\.venv\Scripts\python app.py
```

## Commands

- `/help` shows usage instructions
- `/ask <query>` answers from the local docs
- `/image` waits for an uploaded image
- `/summarize` summarizes the last answer or image result

## Local Web Chat Tester

The local web UI is useful when you want to test the app on your laptop without opening Telegram.

- One chat interface for both text and image testing
- Image attachment directly in the chat composer
- Sidebar for retrieval details, summarize, and reindex
- Same Gemini + local SQLite backend as the Telegram bot

## Example Questions

- `/ask How do I create a Python virtual environment?`
- `/ask Why does this project use Docker?`
- `/ask What should happen when the generation API fails?`
- `/ask What is the recommended git branch flow?`

For image mode:

- Send `/image`
- Upload a photo from your phone
- The bot returns one caption and 3 tags

## Docker

Docker is optional.

```powershell
docker compose up --build
```

The included Docker Compose file still runs the Telegram bot entrypoint by default.

## Running Tests

```powershell
.\.venv\Scripts\pytest
```

The tests use fake embedders and a fake Gemini client, so they run without external API calls.

## Notes

- This is still a hybrid solution: local retrieval plus API-based generation.
- SQLite is enough here because the assignment corpus is intentionally small.
- Long polling is used instead of webhooks to keep local setup simple.
- To swap the sample docs, edit `data/knowledge_base/` and rerun `scripts/reindex.py`.
