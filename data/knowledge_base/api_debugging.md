# API Debugging FAQ

## What should happen when the generation API fails?

The bot should return a clean user-facing error message instead of exposing stack traces or raw provider responses. The technical error should still be logged so developers can diagnose quota issues, invalid credentials, or transient network failures.

## How should RAG answers stay grounded?

The prompt should explicitly tell the model to answer only from retrieved context. If the retrieved snippets do not contain the answer, the model should say that it could not find the answer in the knowledge base instead of guessing.

## What metadata helps with debugging?

Store the user query, the answer, and the source snippets used for the response. For image requests, store the generated caption and tags. This history makes it easier to explain what the bot saw and why it answered in a certain way.

## What is a good fallback for unknown questions?

Return a short response such as "I couldn't find that in the knowledge base." This is safer than sending a weak answer based on loosely related chunks, especially when the knowledge base is intentionally small.
