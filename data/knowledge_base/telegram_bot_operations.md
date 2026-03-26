# Telegram, RAG, Model, and SQLite FAQ

This file blends official Telegram, LangChain, Ollama, Gemini, and SQLite concepts with the exact bot and retrieval behavior implemented in this repository.

## Q001. What commands should the Telegram bot support?

The bot should support `/help`, `/ask`, and `/image`. Those three commands cover the assignment-facing text and image flows without unnecessary extras.

## Q002. What does `/help` do?

It explains how to ask a document question and how to start the image-caption flow. Good help text lowers confusion before users start guessing.

## Q003. What does `/ask` do?

It starts the knowledge-base question flow. The user can send `/ask <query>` directly or send `/ask` first and then send the actual question in the next plain-text message.

## Q004. What does `/image` do?

It switches the bot into an image-waiting state. The next uploaded image is described and tagged instead of being treated as a regular chat message.

## Q005. Why is `/ask` a two-step flow when no query is provided?

The two-step flow makes the interaction clearer for users who first select the command from Telegram's command list. It also prevents plain text outside the intended flow from being interpreted too eagerly.

## Q006. Why is `/image` a two-step flow?

It makes image handling explicit and avoids guessing whether a random later upload should trigger captioning. That makes the user experience more predictable.

## Q007. What should happen after an image is processed?

The bot should clear the waiting state, store the result, and return one short caption plus exactly three tags. Clearing state is important so unrelated later uploads are not misrouted.

## Q008. Why is long polling acceptable for this project?

Long polling is simple to run locally and does not require a public webhook endpoint. For an assignment-sized bot, that simplicity is usually the right tradeoff.

## Q009. What Telegram builder pattern is used in this repo?

The bot uses `ApplicationBuilder` from `python-telegram-bot`. That is the standard modern entry point for building a polling bot.

## Q010. Which handler types matter most here?

`CommandHandler` is used for commands and `MessageHandler` is used for text and image uploads. The handler mix reflects the assignment's simple command-driven UX.

## Q011. Why use a `MessageHandler` for photos and image documents?

Telegram can send images as photos or as files with image MIME types. Supporting both covers the most common user upload paths.

## Q012. Why should unknown commands return a clear message?

Silent failure is confusing. A short unknown-command response teaches the user which commands are actually supported.

## Q013. Why restrict plain text outside active flows?

It prevents the bot from pretending to be a free-form assistant when the assignment only requires specific flows. Clear boundaries reduce unexpected behavior.

## Q014. What should the help text communicate clearly?

It should explain `/ask`, `/image`, and the fact that `/image` returns one caption plus three tags. Users should know both the command format and the scope of the bot.

## Q015. What startup calls should appear in healthy Telegram logs?

You should normally see `getMe`, `setMyCommands`, `deleteWebhook`, and then long-polling activity such as `getUpdates`. That sequence shows the bot authenticated and started correctly.

## Q016. What indicates that polling is healthy?

Repeated `getUpdates` requests with `HTTP/1.1 200 OK` are a strong sign that polling is active. They show the bot is alive and talking to Telegram successfully.

## Q017. What causes the Telegram conflict error with polling?

It happens when more than one process polls the same bot token at once. Telegram expects a single active poller for one bot token.

## Q018. How do I fix a duplicate-polling conflict?

Stop the older bot process and restart only one clean instance. Once the duplicate poller is gone, the conflict usually disappears immediately.

## Q019. How are sources shown back to users now?

The bot shows the source file path and the section heading. That gives users traceability without dumping long snippets into the chat.

## Q020. Why show file path plus heading instead of a long snippet?

It is easier to scan and tells the user exactly where the answer came from. Long snippets are noisier and often redundant if the answer itself is already concise.

## Q021. What does knowledge-base search do at a high level?

It normalizes the query, gets or computes an embedding, scores all stored chunks, filters low-score matches, and returns the top results. This is a simple dense-vector RAG pipeline.

## Q022. How are documents split before retrieval?

They are first broken by Markdown headings and then chunked with a recursive text splitter. That means good headings strongly influence retrieval quality.

## Q023. What does `chunk_size=700` mean in this repo?

It means each chunk aims to stay around 700 characters under the configured splitter. This balances context density against chunk fragmentation.

## Q024. What does `chunk_overlap=100` mean?

It means adjacent chunks share about 100 characters of overlap. Overlap helps preserve context that would otherwise be cut apart at chunk boundaries.

## Q025. Which embedding model is used?

The project uses `sentence-transformers/all-MiniLM-L6-v2`. It is a lightweight sentence-embedding model suitable for local retrieval.

## Q026. Why are embeddings normalized?

Normalization makes dot-product scoring behave like cosine similarity. That gives a stable and simple relevance signal for dense retrieval.

## Q027. What similarity calculation is effectively used here?

Because embeddings are normalized, the dot product acts like cosine similarity. That is the retrieval score used to rank chunks.

## Q028. What does the minimum relevance score do?

It filters out weak matches before final ranking. If the threshold is too high, relevant chunks can be missed; if too low, noisy chunks can slip in.

## Q029. What does `TOP_K=3` mean?

It means the app keeps the top three retrieved chunks for grounded answering. This keeps prompts compact but can miss lower-ranked exact matches.

## Q030. What does `HISTORY_WINDOW=3` mean?

It means the rewrite step looks at the last three turns of conversation history. That is enough for short follow-up context without bloating prompts.

## Q031. What is the rewrite step for?

It rewrites follow-up questions into standalone search queries and can also classify simple greetings. This improves retrieval when the latest message depends on recent chat context.

## Q032. When is the rewrite step skipped?

It is skipped when there is no prior history. In that case, the app usually uses the original question directly as the retrieval query.

## Q033. What is the greeting fast path?

Simple greetings like "hello" can be answered directly without retrieval. This avoids spending retrieval and model work on small talk.

## Q034. Why split routes into `greeting` and `rag`?

Not every message needs a KB search. Routing lightweight social messages away from retrieval saves time and keeps the system behavior cleaner.

## Q035. What should happen if retrieval finds no good sources?

The bot should answer with the exact fallback: `I couldn't find that in the knowledge base.` That is the safest grounded response.

## Q036. What fallback should the app return for unknown knowledge-base questions?

The fallback for unknown knowledge-base questions should be `I couldn't find that in the knowledge base.` Consistency makes the behavior easier to test and easier to trust.

## Q037. What source data is stored with each turn?

The turn payload stores the user message, the assistant reply, and a compact source list. That gives history enough context without storing the entire raw prompt.

## Q038. Why store turns in SQLite?

SQLite is lightweight, local, and good enough for assignment-scale persistence. It avoids the overhead of a separate database service.

## Q039. Which core tables should the SQLite design maintain?

The core tables should be `documents`, `chunks`, `query_cache`, `turns`, and `user_state`. Those tables cover indexing, retrieval, conversation memory, and Telegram flow state.

## Q040. What is the purpose of the `documents` table?

It stores one row per indexed source file along with its path, title, and content hash. This supports reindexing and stale-document cleanup.

## Q041. What is the purpose of the `chunks` table?

It stores each searchable chunk, its heading, its text, and its embedding. This table is the main retrieval surface for the RAG pipeline.

## Q042. What is the purpose of the query cache?

It stores previously computed query embeddings keyed by query hash. That avoids recomputing embeddings for repeated queries.

## Q043. What is the purpose of the `turns` table?

It stores chat and image interactions as JSON turn payloads in the local database. That gives both the bot and the local web app a shared history store.

## Q044. What is the purpose of `user_state`?

It stores per-user flags such as `waiting_for_image` and `waiting_for_ask`. Those flags make the Telegram command flows explicit and safe.

## Q045. Why is query caching helpful?

Query embedding can be expensive compared with a cache hit. Reusing the cached embedding improves repeated-query performance.

## Q046. Why are returned source snippets limited in length?

Short snippets are enough to inspect relevance without bloating the response. Full chunk text is more useful in logs or internal storage than in the user-facing reply.

## Q047. Why does `stream=False` matter in this app?

Non-streaming responses are simpler to handle in both the Telegram bot and the local web app. It also avoids partial-output issues in the current architecture.

## Q048. Why can non-streaming be especially useful for local models?

Some local models can spend a long time reasoning or streaming incremental output that the app does not need. Waiting for one complete final answer keeps the control flow simpler.

## Q049. What does `RAG_MAX_OUTPUT_TOKENS=1024` do now?

It gives the grounded answer step a larger output budget. That helps prevent overly short or clipped RAG answers when the provider can support longer output.

## Q050. When should the extractive fallback be used?

It should be used when the model returns an empty, truncated, too-short, or obviously low-quality answer relative to the retrieved sources. The fallback keeps the system grounded even when generation quality slips.

## Q051. Why do exact literals matter so much in this project?

Users often ask for exact commands, ports, endpoints, class names, or fallback strings. A grounded assistant should preserve those literals when the docs already contain them.

## Q052. Why should command questions prefer exact copy over loose paraphrase?

Commands fail easily when paraphrased incorrectly. If the source includes a literal command, copying it exactly is safer and more useful.

## Q053. What is `ModelGateway` responsible for?

It centralizes model-provider selection and hides provider-specific details from the rest of the app. That keeps the higher-level services simpler.

## Q054. Which text providers are supported?

The project supports `ollama` and `gemini` as text providers. The active provider is selected through environment variables.

## Q055. Which vision providers are supported?

The project supports `ollama` and `gemini` as vision providers too. This keeps text and image paths independently configurable.

## Q056. When is Gemini used for text?

Gemini is used when `TEXT_PROVIDER=gemini`. In that mode, text generation flows through the Gemini-backed path rather than ChatOllama.

## Q057. When is Gemini used for vision?

Gemini is used when `VISION_PROVIDER=gemini`. That route is especially useful when the local Ollama model is not the best fit for image tasks.

## Q058. When is Ollama used?

Ollama is used whenever the corresponding provider variable is set to `ollama`. It remains the main local-model path for offline or local-first usage.

## Q059. Why is provider switching via environment variables useful?

It keeps the architecture plug-and-play instead of hardcoding one provider. That makes experiments and fallbacks easier without rewriting service code.

## Q060. What class is used for local chat generation?

The class used for local chat generation is `ChatOllama`. It handles Ollama-backed text and structured-generation flows through LangChain.

## Q061. What is `ChatGoogleGenerativeAI` used for here?

It is used for Gemini-backed model calls through LangChain. The image path now relies on it for proper structured multimodal output handling.

## Q062. How is image input passed to Gemini through LangChain?

The image is converted to a base64 data URL and sent as a `HumanMessage` content item of type `image_url` alongside a text instruction. That matches LangChain's Gemini multimodal input pattern.

## Q063. Why use structured output for image captioning?

Structured output reduces brittle text parsing and makes the model return a predictable schema. That is especially useful when the bot needs exactly one caption and three tags.

## Q064. What schema does the image path expect?

It expects a schema with `caption` and `tags`. The caption should be one short sentence, and the tags should be exactly three short lowercase strings.

## Q065. Why require exactly three tags?

The assignment expects a fixed small tag set and the UI is simpler with a predictable output shape. It also makes testing much easier.

## Q066. Why keep the image caption short?

A short caption is easier to read in chat and matches the assignment's lightweight bot style. It also reduces the risk of verbose or off-topic image descriptions.

## Q067. What should happen if the model returns malformed image output?

The code should attempt structured parsing first, then fall back to raw-text parsing if needed, and finally raise a generation error if no usable payload exists. This keeps the bot from silently inventing structure.

## Q068. How does the bot respond to an image generation error?

It logs the failure, clears the waiting-for-image state, and tells the user to send `/image` and try again. That prevents the bot from getting stuck in a broken state.

## Q069. Why clear `waiting_for_image` after failure?

If the flag stays true after an error, later messages can be misinterpreted as part of the old image flow. Clearing it makes retries explicit and safe.

## Q070. Why does `waiting_for_ask` exist?

It supports the two-step `/ask` flow. Without it, the bot would not know when the next plain text should be treated as the user's question.

## Q071. How do the web app and Telegram bot share RAG logic?

Both call the same `RagService` and `KnowledgeBase`. That means retrieval and grounded-answer behavior stay aligned across interfaces.

## Q072. Why is the local web app useful for Telegram debugging?

It lets you test the exact same backend flow without Telegram-specific transport issues. This makes it easier to isolate whether the problem is in core logic or bot handling.

## Q073. What does the chat API return besides the reply?

It returns the route, rewritten query, and serialized sources. Those extra fields are useful for debugging retrieval quality.

## Q074. Why are retrieval metrics helpful in logs?

They show how many chunks were scanned, matched, and returned. That gives quick clues about whether poor answers are caused by retrieval or generation.

## Q075. Which log lines are especially important for grounded answers?

`KB search complete`, `RAG retrieval complete`, and `RAG final answer model response` are especially useful. Together they show the retrieval outcome and the model phase timing.

## Q076. What does `KB search complete` tell you?

It tells you how many chunks were scanned, how many met the score threshold, and how many were returned. That is the clearest retrieval health line in the logs.

## Q077. What does `RAG final answer model response` tell you?

It shows timing and model-response metadata for the final answer call. That helps distinguish retrieval issues from provider latency or truncation.

## Q078. What does `Vision model output` tell you?

It shows that the image service successfully produced a caption and tags. If that line appears, the structured image flow likely worked.

## Q079. Why can hallucinations still happen in a RAG system?

The model can still overgeneralize or fill gaps if prompts, retrieval, or answer constraints are weak. RAG reduces hallucination risk, but it does not eliminate it automatically.

## Q080. What is the best first move when hallucinations appear?

Improve grounding and refusal behavior before chasing model creativity. In practice that means better retrieval, stronger fallback rules, and clearer answer constraints.

## Q081. Why should unsupported topics be refused?

A grounded assistant should not answer beyond its documents. Refusal is often more trustworthy than a confident but ungrounded guess.

## Q082. What if the user asks for an AWS region that is not in the docs?

The bot should answer with `I couldn't find that in the knowledge base.` That is the correct grounded behavior for unsupported topics.

## Q083. Should the bot ever invent details to sound helpful?

No. Sounding confident is not the same as being grounded, and invented details damage trust faster than a short honest refusal.

## Q084. Why can dense-only retrieval miss exact command questions?

Dense embeddings are good at semantic similarity, but exact literal strings can be outranked by broader conceptual matches. That is why heading quality and fallback logic matter.

## Q085. Why do heading-rich docs help retrieval?

The splitter preserves headings as chunk metadata, and questions often overlap with heading vocabulary. Strong headings make exact intent easier to match.

## Q086. Why can four larger FAQ files still work well for retrieval?

The splitter still breaks them into many heading-based chunks, so retrieval operates over sections, not whole files. That preserves granularity while reducing KB clutter.

## Q087. What if the query cache hits but the docs changed recently?

The query cache only stores query embeddings, not old answer text. Reindexing updates the documents and chunks, so cached query embeddings can still be reused safely.

## Q088. What if the database still references removed docs?

Reindex compares on-disk files to indexed paths and removes stale document rows. That keeps deleted files from lingering in retrieval results.

## Q089. What does a zero-source answer usually mean?

It usually means no chunk passed the relevance threshold or the query truly is unsupported by the KB. That should lead to the explicit fallback response.

## Q090. Why might text and image use different providers?

Different providers have different strengths, costs, and latency patterns. Separating the choices lets the app pick the best tool for each task.

## Q091. What if a local Ollama model is too slow for chat?

Consider switching the text provider or using a faster model. Retrieval may be fine while generation latency makes the overall experience feel broken.

## Q092. What if Gemini answers are too brief?

Increase the output budget or relax over-compression in the prompt. A provider can be fast and still need prompt or token-budget tuning for answer completeness.

## Q093. Why were the heavy eval harnesses optional rather than runtime features?

They are useful for benchmarking but not necessary for normal operation. The bot itself only needs the runtime services and indexed documents to function.

## Q094. What manual Telegram bot smoke tests should always be run?

Test `/help`, ask one known-good `/ask` question, and run one `/image` upload. Those three checks cover the required assignment-facing flows.

## Q095. What manual image smoke test should confirm success?

The test should confirm that the bot returns one caption and exactly three tags. The logs should also show the vision flow completing without a generation error.

## Q096. Which logs prove that an image request succeeded?

Look for `Vision start`, `Vision image normalized`, `ModelGateway vision model`, `Vision model output`, and `Vision turn stored`. That sequence shows a full successful image flow.

## Q097. What is the core safety rule for this project?

The core safety rule for this project is to use only retrieved or indexed knowledge-base material and refuse unsupported questions. That rule matters more than sounding broadly intelligent.

## Q098. Why is source transparency important in a grounded bot?

It helps users verify where answers came from and makes debugging retrieval much easier. Visible sources reinforce trust when the answer is correct and reveal issues when it is not.

## Q099. What is the best short manual quality checklist for a reply?

Check whether the answer is relevant, whether it matches the source file and heading, and whether it avoids inventing unsupported details. If any of those checks fail, the reply is not good enough.

## Q100. What is the best one-line summary of the project architecture?

This project is a Telegram-and-FastAPI bot that uses LangChain-managed model providers, SQLite-backed retrieval memory, and a heading-chunked local knowledge base to answer grounded text and image requests.
