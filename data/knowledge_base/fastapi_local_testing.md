# FastAPI, Local Web App, and API Testing FAQ

This file combines official FastAPI and Uvicorn guidance with the exact local routes and behavior implemented in this repository.

## Q001. What is FastAPI used for in this project?

FastAPI powers the local browser-based tester. It gives the same core RAG and image flows a simple HTTP interface for debugging and validation.

## Q002. Why keep a local web app if Telegram is the main interface?

The local web app is faster to debug because it avoids Telegram round trips. It is also easier to inspect request and response behavior in a browser or API client.

## Q003. What command starts the local web app?

Run `python web_app.py` from the project root. That calls the `run()` function in the web app module and starts Uvicorn.

## Q004. Where is the real FastAPI app created?

The app is created in `src/omniquery_bot/web_app.py` by the `create_app(...)` function. The root `web_app.py` file is just a thin launcher.

## Q005. Why use an app factory instead of a single global app object?

An app factory makes tests and dependency injection easier. It lets the code pass fake services or special settings into the app without patching module globals.

## Q006. What does `create_app(...)` wire together?

It validates settings, initializes the knowledge base if needed, creates the model gateway, builds the RAG and vision services, and mounts the local web assets.

## Q007. What does the root `/` endpoint return?

It returns the local `index.html` file from the web assets directory. That file loads the small browser UI for testing the bot locally.

## Q008. What does `/api/health` do?

It returns a simple health payload such as `{"status": "ok"}`. This is the fastest endpoint for checking whether the server is alive.

## Q009. Which endpoint returns the active runtime configuration?

The endpoint that returns the active runtime configuration is `/api/config`. It returns non-secret runtime settings such as the text model, vision model, embedding model, KB path, `top_k`, and `history_window`.

## Q010. What does `/api/history` return?

It returns recent user and assistant messages for a given session id. The payload is built from stored turns in SQLite.

## Q011. What does `/api/chat` do?

It accepts a session id and a message, runs the RAG flow, and returns the reply, route, rewritten query, and serialized sources. This is the main text-chat endpoint.

## Q012. What does `/api/image` do?

It accepts a session id and an uploaded file, runs the image-description flow, and returns the caption, tags, and formatted reply. It mirrors the Telegram image workflow in HTTP form.

## Q013. What should happen when I click reindex?

When you click reindex, the app should call `/api/reindex`, trigger knowledge-base reindexing, and return indexing statistics. This is useful after editing KB documents.

## Q014. Why does the local app default to `127.0.0.1:8000`?

That is a standard local development default and keeps the service private to the machine unless the host is changed. It is a safe default for an assignment-style local tester.

## Q015. How can I change the host or port?

Set `WEB_HOST` and `WEB_PORT` before starting the server. The `run()` function reads those environment variables before launching Uvicorn.

## Q016. Why are static files mounted at `/static`?

Mounting a static directory gives the HTML page a clean path for its JavaScript and CSS assets. It is the normal FastAPI pattern for local frontend assets.

## Q017. Why use `FileResponse` for the index route?

It serves the HTML file directly from disk. That keeps the launcher simple and avoids template-engine complexity for a small local tester.

## Q018. Why use `UploadFile` for image uploads?

`UploadFile` is the standard FastAPI way to handle file uploads efficiently. It fits the image-caption use case without forcing the client to inline image bytes as JSON.

## Q019. Why use `Form(...)` for the image session id?

Multipart uploads mix files and text fields, so the session id is passed as a form field. That is the usual way to pair metadata with an uploaded file.

## Q020. Why use a Pydantic model for chat requests?

A typed request model validates the incoming JSON shape and makes the handler contract explicit. It also keeps the endpoint code easier to read.

## Q021. Which fields are required in the chat request body?

The request needs `session_id` and `message`. Both are required for the chat route to work correctly.

## Q022. Why normalize the session id?

The app strips whitespace and rejects empty values so storage and retrieval stay consistent. This avoids accidental empty-session writes and confusing history behavior.

## Q023. Why strip the message before processing?

Leading and trailing whitespace often adds no value, and a blank message should not hit the RAG pipeline. Stripping the value makes validation straightforward.

## Q024. What happens if `/api/chat` gets an empty message?

The endpoint returns HTTP `400`. The error indicates a client-side input problem rather than a model or server failure.

## Q025. Why run heavy work in a threadpool?

RAG, reindexing, and image processing can block. Running them in a threadpool keeps the async web server responsive while the synchronous work runs in the background.

## Q026. What is `run_in_threadpool` doing here?

It hands synchronous functions to a worker thread while preserving the async API surface. This is a common FastAPI pattern when the underlying code is not async-native.

## Q027. Why does the app reindex the knowledge base on startup?

Startup reindexing keeps the app aligned with the current KB files. That means fresh document changes are noticed automatically when the server starts.

## Q028. Why log KB sync statistics on startup?

The counts quickly show whether the app saw the expected files, reindexed anything, or removed stale documents. Those numbers are a cheap but valuable debugging signal.

## Q029. What is the expected startup sequence?

The app should validate settings, sync the knowledge base, create services, mount static files, and then start Uvicorn. After that, requests should begin returning `200 OK`.

## Q030. How can I quickly verify the app is running?

Open `http://127.0.0.1:8000/` in a browser or call `/api/health`. Either check should confirm the process is listening and serving.

## Q031. How do I use the browser tester?

Start the server, open the root page, and use the built-in UI to ask questions or upload images. The browser tester is a convenience layer over the API routes.

## Q032. How do I test `/api/health` from a terminal?

Use a simple GET request such as `curl http://127.0.0.1:8000/api/health`. The expected response is a small JSON health payload.

## Q033. How do I test `/api/config`?

Send a GET request to `/api/config`. That route is useful for checking which model names and retrieval settings the app currently exposes.

## Q034. How do I test `/api/chat` manually?

Send a JSON POST body with `session_id` and `message`. The response should include a grounded reply and a source list when retrieval succeeds.

## Q035. How do I test `/api/history` manually?

Call `/api/history?session_id=<value>` after sending at least one chat request. The endpoint should return alternating user and assistant messages for that session.

## Q036. How do I test `/api/image` manually?

Send a multipart request with `session_id` and an image file. The response should return a caption, three tags, and the formatted reply string.

## Q037. How do I test `/api/reindex` manually?

Send a POST request to `/api/reindex` after editing KB files. The returned stats show how many files were seen, reindexed, removed, and chunked.

## Q038. What fields come back from `/api/chat`?

The route returns `reply`, `route`, `rewritten_query`, and `sources`. This makes the API useful for both debugging and UI rendering.

## Q039. What fields come back from `/api/image`?

The route returns `reply`, `caption`, `tags`, and `file_name`. That is enough for a simple frontend to show both the raw structured result and the user-facing message.

## Q040. What shape does `/api/history` use?

It returns a `messages` array with alternating user and assistant entries. Assistant image messages can also include tags.

## Q041. What does source serialization include?

Each source includes a chunk id, file name, document path, heading, score, and a shortened snippet. That is a good balance between transparency and response size.

## Q042. Why are snippets shortened before returning them?

Short snippets make the UI easier to scan and prevent the API from sending large blocks of context text back to the client. The full text still exists in the KB store.

## Q043. Why return both file name and heading?

The file name tells the user which document answered the question, and the heading tells them which section was most relevant. Together they are more helpful than a raw chunk id.

## Q044. How are `400`, `502`, and `500` used differently?

`400` covers bad input, `502` covers generation-provider failures, and `500` covers unexpected server-side issues. That distinction makes debugging faster.

## Q045. When does the web app return `502`?

It returns `502` when a `GenerationError` comes from the model layer. This signals that the app ran correctly but the provider path failed.

## Q046. When does the web app return `400`?

It returns `400` for invalid input such as an empty message, bad session id, or invalid uploaded image. These are client-side request problems.

## Q047. When does the web app return `500`?

It returns `500` for unexpected internal failures that the app did not classify more specifically. Those errors should be investigated through logs.

## Q048. Why not expose stack traces to end users?

Stack traces are noisy, leak internals, and are not user-friendly. Logs are the right place for deep diagnostics, not the public HTTP response body.

## Q049. Where do the web assets live?

They live in the top-level `web` directory. The FastAPI app mounts that directory as its static asset source.

## Q050. What happens if the `web` directory is missing?

The app raises a `FileNotFoundError` on startup. That prevents a half-working state where the API is up but the browser UI is broken.

## Q051. How do the web app and Telegram bot share logic?

Both call the same `RagService`, `VisionService`, `ModelGateway`, and `KnowledgeBase`. This keeps behavior aligned across interfaces.

## Q052. Why is shared service logic important?

It means a fix to retrieval, prompting, or image handling benefits both interfaces at once. That lowers maintenance cost and reduces divergence bugs.

## Q053. Why is the web app a good place to debug Telegram issues?

The web app removes Telegram transport concerns and exposes the same core behavior locally. If the web path works and Telegram fails, the bug is probably in bot flow or polling.

## Q054. How does a web session id differ from a Telegram user id?

A web session id is an arbitrary local identifier chosen by the client. A Telegram user id comes from Telegram and is tied to the real bot user.

## Q055. Why does the history API load the last 12 messages worth of turns?

It is enough for the local tester to show recent context without returning an unbounded history. The assistant still uses a smaller history window internally for rewriting.

## Q056. Why can the UI show more history than the RAG rewrite step uses?

The UI is for human inspection, while the rewrite step is tuned for a focused prompt budget. Those two needs are related but not identical.

## Q057. What if `/api/chat` feels slow?

Check provider latency, model choice, and retrieval timings in the logs. Local model generation is usually the biggest bottleneck, not FastAPI itself.

## Q058. Which logs are most useful for a slow chat request?

Look for retrieval timing, model-response timing, and source count logs. Those lines show whether the slowdown is search, generation, or both.

## Q059. What if `/api/chat` returns an empty-looking answer?

Check whether the provider truncated or failed to parse output, and inspect the fallback logs. The app already has guardrails to replace weak answers with extractive fallback when needed.

## Q060. What if image upload fails in the web app?

Check the vision-provider logs and confirm the uploaded file is a valid image. Then verify the selected vision provider and model are compatible with the current path.

## Q061. What if `/api/reindex` reports no changes after editing docs?

Make sure you edited files under `data/knowledge_base` and saved them. Reindex compares file hashes, so unchanged saved content will correctly show no reindex.

## Q062. Why are chunk counts useful?

Chunk counts show whether the document splitter is actually seeing enough content. A surprisingly low chunk count often means the KB is too small or too shallow.

## Q063. Why does source count matter?

A source count of zero means the final answer had no retrieval backing. A very low or unstable count can point to query mismatch or overly strict thresholds.

## Q064. Can the web app run without Telegram?

Yes. The web app is a self-contained local tester and does not require Telegram polling to be active.

## Q065. Can the web app run without the `web` assets?

The browser UI cannot, but the API routes are conceptually separate. In this codebase, startup intentionally fails early if the `web` directory is missing.

## Q066. Why is FastAPI a good fit for assignment-level tooling?

It is lightweight, typed, and easy to wire to existing Python services. It also makes manual and automated testing very straightforward.

## Q067. How does `TestClient` help in this repo?

It lets tests call the app directly without starting a real network server. That makes endpoint tests fast and deterministic.

## Q068. What does `python -m pytest` verify here?

It verifies the RAG flow, web endpoints, knowledge-base behavior, and image-service behavior at the unit and local integration level. It is the main regression safety net.

## Q069. Why make dependencies injectable in `create_app(...)`?

Injection makes the app easy to test with fake knowledge bases and fake model gateways. That removes a lot of slow and flaky external dependencies from tests.

## Q070. How do fake gateways help?

They replace live model calls with deterministic responses. That keeps tests fast while still exercising the route logic and serialization behavior.

## Q071. What should `/api/health` return in a healthy state?

A simple `{"status": "ok"}` payload is enough. Health endpoints should stay boring and stable.

## Q072. Should `/api/config` expose secrets?

No. It should only expose safe operational metadata such as model names and retrieval settings.

## Q073. Why show model names but not API keys in config?

Model names help debugging, while API keys are sensitive secrets. The config endpoint is intentionally designed to expose only safe runtime metadata.

## Q074. How can I confirm the active knowledge-base path?

Call `/api/config` and inspect the `knowledge_base` field. That confirms the directory the runtime thinks it is using.

## Q075. Why might response models be added later?

They can make API contracts even stricter and easier to document. For this assignment-sized app, the current dictionary responses keep the code compact.

## Q076. Why is answer-length control mostly handled in the model layer?

The grounded-answer prompt and token settings already shape response size. Truncating aggressively at the API layer could hide useful answer content.

## Q077. What if the browser seems to show stale JavaScript or CSS?

You may be seeing a cached frontend asset. A hard refresh or cache clear usually fixes that during local development.

## Q078. Are `304 Not Modified` responses for static assets normal?

Yes. They mean the browser is reusing cached versions of unchanged assets rather than downloading them again.

## Q079. How do I clear stale frontend cache quickly?

Use a hard refresh in the browser or clear the specific site cache. That is often enough after editing local UI files.

## Q080. What if port `8000` is already in use?

Either stop the other process or start the app with a different `WEB_PORT`. Port conflicts are a common local-development issue and not a FastAPI bug.

## Q081. How do I run the web app on another port?

Set `WEB_PORT` before launch, then start `python web_app.py` again. The `run()` helper reads that environment variable on startup.

## Q082. Why mount static assets under `/static` instead of the root?

It avoids clashing with API routes and keeps HTML, JS, and CSS paths consistent. This is the standard web-app split between app routes and asset routes.

## Q083. What is the role of `FileResponse(WEB_DIR / "index.html")`?

It serves the local entry HTML directly without a templating layer. That keeps the local UI path simple and predictable.

## Q084. How are uploaded images handled by the API?

The endpoint reads the bytes from the uploaded file, passes them to the vision service, and returns a structured result. Validation errors become `400`, while model errors become `502`.

## Q085. When would background tasks be better than the current threadpool pattern?

Background tasks help when the client should not wait for completion. Here the client wants the final answer immediately, so the threadpool pattern fits better.

## Q086. Does the local API stream responses?

No. It currently returns completed responses. That keeps the browser tester simpler and avoids partial-output handling.

## Q087. Why is non-streaming acceptable for this assignment?

It reduces frontend complexity and still supports all required flows. For a local tester, simplicity is often more valuable than fancy response streaming.

## Q088. What happens if the session id is missing or blank?

The normalization logic rejects it and the route returns a client error. Session ids are required because turn history depends on them.

## Q089. What if the uploaded image has no MIME type?

The code falls back to a generic content type string if needed, then still tries to process the image bytes. The vision service ultimately validates whether the file is a real image.

## Q090. Why does session-id normalization matter so much?

History, retrieval context, and storage all depend on stable identifiers. Tiny whitespace mismatches could otherwise create separate conversation histories by accident.

## Q091. How can I see incoming request logs?

Watch the terminal running the app or tail the log file if you redirected output. The app logs route-level events such as config, chat, history, image, and reindex requests.

## Q092. How can I see outgoing response details?

The route logs include response summaries such as route, rewritten query, source count, caption, or tags. Those logs are often enough without needing full payload dumps.

## Q093. What should `/api/reindex` return after a document change?

It should report at least one file reindexed and a nonzero chunk count for the changed document set. If it does not, the change may not have been saved where the app expects it.

## Q094. How can I tell whether stale documents were removed?

Look at the `files_removed` count in the reindex stats. That count increases when indexed docs no longer exist on disk.

## Q095. Why use the local tester before Telegram?

It is faster and easier to debug. If the local tester fails, there is no point debugging Telegram yet because the shared core flow is already broken.

## Q096. What is a good end-to-end manual test after a backend change?

Check `/api/health`, then ask one known-good chat question, then upload one known-good image, and finally call `/api/history`. That covers the main local web flows.

## Q097. What if source snippets look unrelated to the answer?

That usually points to retrieval quality, document structure, or thresholds rather than the web framework itself. The web app is only showing what the backend retrieved.

## Q098. How do I verify the exact file names in the returned sources?

Check the `file_name` and `document_path` fields in the chat response. They are serialized directly from the retrieved KB matches.

## Q099. What should I check after changing KB documents?

Reindex first, then call `/api/chat` with known questions and inspect the returned sources. That confirms both indexing and retrieval are seeing the new document content.

## Q100. What is the best short local web debugging checklist?

Start the server, confirm `/api/health`, confirm `/api/config`, ask one known question, upload one known image, and inspect the logs if anything looks off. That sequence catches most local API issues quickly.
