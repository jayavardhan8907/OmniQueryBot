# Architecture and Design Notes

## Purpose

This document explains the actual system design of OmniQueryBot, why each component exists, which models/providers are used, and what the main benefits and tradeoffs are.

The goal is not just to say what the bot does, but to explain why this implementation is a sensible answer to the assignment brief.

## Assignment Mapping

The brief allows:

- Telegram or Discord
- a lightweight RAG bot, or
- a lightweight image-description bot

This project implements the stronger hybrid version:

- Telegram bot interface
- Mini-RAG text answers
- image captioning + tagging

That means the bot covers both assignment tracks in one codebase.

## High-Level Architecture

```text
Telegram User
    |
    v
python-telegram-bot
    |
    v
bot.py
    |
    +-------------------+
    |                   |
    v                   v
RagService          VisionService
    |                   |
    v                   v
ModelGateway         ModelGateway
    |                   |
    v                   v
Ollama / Gemini      Ollama / Gemini
    |
    v
KnowledgeBase (SQLite + embeddings + turn history)
```

There is also an optional local FastAPI path for debugging:

```text
Local Browser / API Client
    |
    v
FastAPI web_app.py
    |
    v
same RagService / VisionService / KnowledgeBase
```

## Main Components

### 1. `bot.py`

Responsibilities:

- register `/help`, `/ask`, `/image`
- manage two-step Telegram flows
- download Telegram image uploads
- call the shared backend services
- format source paths back to the user

Why this design:

- keeps Telegram-specific code isolated
- keeps business logic out of the bot framework layer

Benefit:

- the bot remains thin and readable

Tradeoff:

- some user-flow state still has to be managed explicitly

### 2. `knowledge_base.py`

Responsibilities:

- scan Markdown/text documents
- split them into chunks
- generate embeddings
- store:
  - documents
  - chunks
  - query cache
  - turns
  - user state
- run retrieval

Why this design:

- SQLite is enough for a small assignment project
- it avoids the overhead of a separate vector database service

Benefits:

- extremely lightweight
- easy local setup
- no extra infrastructure

Tradeoffs:

- no ANN index
- retrieval is simple dense search over stored chunks
- exact literal questions can still be tricky without good FAQ wording

### 3. `rag_service.py`

Responsibilities:

- load recent turns
- decide greeting vs RAG
- optionally rewrite follow-up questions
- retrieve top-k chunks
- build the grounded prompt
- call the final text model
- fall back extractively if the model answer is poor

Why this design:

- separates retrieval behavior from Telegram behavior
- keeps the RAG flow easy to test

Benefits:

- modular
- clear logging
- easier to benchmark

Tradeoffs:

- more moving parts than a single "send prompt to model" design
- rewrite + retrieval + answer means more total latency than a direct reply

### 4. `vision_service.py`

Responsibilities:

- normalize images
- call the vision model path
- validate caption + tag output
- store the result in history

Why this design:

- image processing is a separate concern from text RAG

Benefits:

- keeps image flow self-contained
- easier to swap vision providers

Tradeoffs:

- a second model path increases configuration complexity

### 5. `llm_service.py`

Responsibilities:

- expose one gateway for:
  - text generation
  - structured text generation
  - image description
- hide provider-specific details for:
  - Ollama
  - Gemini

Why this design:

- the assignment rewards clear system design
- provider-switching logic belongs in one place

Benefits:

- plug-and-play model/provider selection
- shared logging and error handling
- easier experimentation

Tradeoffs:

- the abstraction layer adds some code complexity
- lowest-common-denominator behavior must be handled carefully

## Why Telegram Instead of Discord

Telegram was chosen because:

- `python-telegram-bot` is mature and simple
- long polling is easy to run locally
- image upload and command flows are straightforward

Benefits:

- low setup friction
- great for assignment demos
- no webhook requirement for local development

Tradeoff:

- Telegram command UX shapes the design more than a raw chat UI would

## Why This Is a Hybrid Bot

The assignment allowed:

- Mini-RAG only
- Vision only
- or hybrid

This project uses the hybrid approach because it demonstrates:

- document retrieval
- grounded prompting
- multimodal handling
- user-state management

Benefit:

- stronger demonstration of system design

Tradeoff:

- more code and more testing surface than a single-mode bot

## Retrieval Design

### Knowledge Base Strategy

The current knowledge base intentionally uses 4 larger FAQ-style files rather than many small files.

Why:

- fewer files are easier to manage
- the splitter still creates many heading-based chunks
- the FAQ format improves exact question matching

Current shape:

- 4 Markdown files
- about 100 FAQ entries per file
- about 404 chunks after indexing

### Chunking Strategy

Settings:

- `chunk_size = 700`
- `chunk_overlap = 100`

Why:

- large enough to keep a short answer and its local explanation together
- small enough to avoid stuffing too much unrelated context into a chunk

Benefit:

- good balance for short FAQ-style knowledge docs

Tradeoff:

- exact command questions can still compete with nearby semantically similar chunks

### Embedding Model Choice

Chosen model:

- `sentence-transformers/all-MiniLM-L6-v2`

Why:

- lightweight
- fast on CPU
- common and stable for small local retrieval tasks

Benefits:

- small footprint
- fast indexing
- no need for heavier embedding infrastructure

Tradeoffs:

- not state-of-the-art retrieval quality
- dense-only search may underperform on exact literal questions

## Storage Design

SQLite stores:

- `documents`
- `chunks`
- `query_cache`
- `turns`
- `user_state`

Why SQLite:

- assignment explicitly allows local SQLite
- zero extra services
- easy to inspect and reset

Benefits:

- simple deployment
- no networked database dependency
- great fit for local demos

Tradeoffs:

- not ideal for large-scale concurrent workloads
- no advanced vector index by default

## Text Model Strategy

The project supports both local and API-backed text generation.

### Option 1: Ollama

Used through:

- `ChatOllama`

Why keep it:

- local-first
- privacy-friendly
- good fit for "small model footprint" reasoning

Benefits:

- runs locally
- no per-request API dependency

Tradeoffs:

- slower under concurrent load
- smaller local models can overthink or truncate

### Option 2: Gemini

Used through:

- direct Gemini text path in the gateway

Why keep it:

- much faster in practice during local evaluation
- useful fallback when local models are too slow

Benefits:

- low latency
- stable request handling

Tradeoffs:

- requires network access
- requires API credentials
- not purely local

## Vision Model Strategy

The project supports:

- Ollama vision path
- Gemini vision path

### Why Gemini Is a Strong Current Choice for Vision

In this repo, Gemini became the more reliable image path because:

- it handled structured caption/tag output more consistently
- it worked well through LangChain multimodal structured output

Benefits:

- strong multimodal support
- easier caption + 3-tag schema handling

Tradeoffs:

- API dependency
- not fully local

### Why Ollama Vision Support Is Still Kept

Keeping Ollama vision support matters because:

- the assignment explicitly mentions local/open-source models
- a reviewer may prefer a local-only mode

Benefit:

- project remains flexible

Tradeoff:

- local multimodal quality can vary more by model

## Why LangChain Is Used

LangChain is used for:

- prompt assembly
- ChatOllama integration
- ChatGoogleGenerativeAI integration
- structured output
- multimodal message formatting

Why this is reasonable:

- it reduces provider-specific boilerplate
- it simplifies switching between model providers
- it helps keep the code modular

Benefits:

- cleaner orchestration
- structured output support
- easy provider swapping

Tradeoffs:

- extra abstraction layer
- another dependency to understand and debug

## Prompting Strategy

### Rewrite Prompt

Purpose:

- classify greeting vs RAG
- rewrite follow-up messages into standalone questions

Why:

- follow-up questions are common in chat
- retrieval works better with a standalone query than with vague pronouns or context-dependent fragments

### Grounded Answer Prompt

Purpose:

- restrict the answer to retrieved context
- copy exact literals when present
- refuse unsupported answers

Why:

- this project should be grounded, not a free-form chatbot

Benefit:

- better source faithfulness

Tradeoff:

- answers may be shorter or more rigid than a general assistant

## Caching and Efficiency

Implemented:

- query embedding cache
- recent-turn window instead of full-history prompting
- top-k retrieval instead of dumping the entire KB
- non-streaming responses

Why these choices matter:

- they reduce repeated work
- keep prompts smaller
- simplify the runtime path

Tradeoffs:

- the system is optimized for simplicity, not maximal throughput

## Why `stream=False` Was Chosen

The app explicitly avoids streaming in the critical text path.

Why:

- easier Telegram and web-app control flow
- no partial output assembly
- easier fallback handling when an answer is too short or low quality

Benefit:

- simpler app behavior

Tradeoff:

- the user does not see incremental tokens arriving

## Why `RAG_MAX_OUTPUT_TOKENS=1024` Was Added

The answer budget was increased because shorter limits were clipping or over-compressing grounded answers.

Benefit:

- more room for complete grounded responses

Tradeoff:

- potentially longer generation latency

## Image Flow Design

Flow:

1. User sends `/image`
2. Bot sets `waiting_for_image = true`
3. User uploads a photo or image file
4. Image is normalized to JPEG
5. Vision model returns:
   - `caption`
   - `tags`
6. Tags are normalized to exactly 3 unique lowercase values
7. Turn is stored in SQLite

Why this is good design:

- explicit state is easier than guessing intent from random uploads

Tradeoff:

- slightly more guided than a free-form multimodal chat UI

## RAG Flow Design

Flow:

1. User sends `/ask <query>` or `/ask` then a plain message
2. Bot loads recent turns
3. Router decides greeting vs RAG
4. Query is rewritten when needed
5. Top-k chunks are retrieved
6. Grounded prompt is built
7. Model generates final answer
8. Source file paths + headings are returned
9. Turn is stored

Why this is a good assignment fit:

- it is small enough to explain
- modular enough to show design skill
- grounded enough to demonstrate responsible GenAI behavior

## Error Handling Strategy

The project uses explicit fallbacks for:

- bad images
- provider failures
- empty or malformed output
- unsupported knowledge-base questions

Why:

- failure behavior is part of system design, not just a bug path

Benefits:

- safer UX
- easier debugging

Tradeoffs:

- more defensive code
- more branches to test

## Logging and Observability

The project logs:

- startup sync stats
- retrieval steps
- provider calls
- image flow timing
- generation failures
- API request summaries

Why:

- without logs, RAG debugging becomes guesswork

Benefit:

- faster diagnosis of:
  - retrieval misses
  - provider slowness
  - bot-flow errors

Tradeoff:

- too much logging can become noisy if not curated

## Benefits of the Current Architecture

- simple enough for an assignment
- modular enough to explain well
- supports both required modes
- uses lightweight local retrieval storage
- keeps model/provider choices flexible
- easy to test and reason about

## Main Tradeoffs and Limitations

- dense-only retrieval is not perfect for exact literals
- SQLite is great locally but not a scale-out design
- Gemini gives speed but is not fully local
- Ollama gives locality but can be slower
- optional FastAPI path depends on local web assets if used

## Why This Is a Good Submission

This design matches the evaluation criteria well:

- Code Quality:
  - modular services
  - readable separation of concerns
- System Design:
  - clear request flow
  - clear data flow
- Model Use:
  - explicit reasoning for local vs API choices
- Efficiency:
  - caching
  - lightweight embedding model
  - SQLite storage
- User Experience:
  - clear commands
  - grounded responses
  - explicit image output format
- Innovation:
  - hybrid text + image support in one bot

## Short Final Summary

OmniQueryBot is a modular hybrid Telegram bot that uses SQLite-backed retrieval for text answers and structured multimodal generation for image captioning, with provider abstraction so the same codebase can run in local-first or API-backed modes depending on the chosen tradeoff between speed, simplicity, and locality.
