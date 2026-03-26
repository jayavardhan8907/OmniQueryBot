# Docker, Git, Logging, and Validation FAQ

This file combines practical Docker guidance from official Docker docs with project-specific container behavior, plus the minimal git and validation practices that support this repository.

## Q001. What problem does Docker solve?

Docker packages an application and its dependencies into a reproducible container image. That makes local setup and handoff more consistent across machines.

## Q002. What is the difference between an image and a container?

An image is a reusable build artifact, while a container is a running instance of that image. You build images and run containers from them.

## Q003. What does `docker-compose.yml` do in this repo?

It defines how the local service should run with Docker Compose. In this project, it describes a single bot service with its environment file, data mount, and startup command.

## Q004. How many services are currently defined in `docker-compose.yml`?

There is one service named `bot`. That keeps the compose setup intentionally simple for local assignment use.

## Q005. What command does the compose service run?

It runs `python app.py`. That starts the Telegram bot inside the container.

## Q006. Why is `env_file: .env` used?

It injects runtime configuration into the container without hardcoding secrets in the compose file. That is cleaner and safer than repeating all variables inline.

## Q007. Why is `./data:/app/data` mounted as a volume?

It persists the SQLite database and knowledge-base data outside the container image. That means container rebuilds do not wipe the local runtime data directory.

## Q008. Why build from a Dockerfile instead of using a generic Python image directly?

The Dockerfile captures the exact app packaging steps for this repository. That makes the container behavior reproducible instead of relying on manual commands every time.

## Q009. What Docker command should I use to build and start the service?

Run `docker compose up --build`. That builds the image if needed and then starts the service.

## Q010. What Docker command stops the service?

The Docker command that stops the service is `docker compose down`. It stops and removes the running compose-managed container.

## Q011. How do I run the compose service in the background?

Run `docker compose up -d`. Detached mode is useful when you want the service running but do not want the terminal occupied.

## Q012. How do I follow compose logs live?

Run `docker compose logs -f`. This is the easiest way to watch startup, request, and error logs from the running service.

## Q013. How do I see container status in Compose?

Run `docker compose ps`. It shows whether the service is up, exited, or restarting.

## Q014. How do I restart the service after a config change?

Run `docker compose down` and then `docker compose up --build` if the image changed, or `docker compose up -d` if only runtime state needs refreshing. Restarting ensures new environment values are loaded.

## Q015. When should I rebuild with `--no-cache`?

Use `docker compose build --no-cache` when you suspect stale build layers are hiding dependency or file changes. It is slower but removes cache ambiguity.

## Q016. Why mount the data directory instead of baking it into the image?

Baking runtime data into the image makes updates and persistence awkward. A bind mount keeps the database, knowledge base, and generated state under your control on the host.

## Q017. What kinds of files normally live in `data/`?

The SQLite database and knowledge-base documents live there. Temporary logs or test artifacts may appear too, but those are usually runtime clutter rather than core source files.

## Q018. Should the Docker image bundle Ollama too?

Usually no for this project. Keeping the bot app and the local model runtime separate is simpler, lighter, and easier to debug.

## Q019. Why keep Ollama outside the main bot container?

Local model runtimes have their own resource needs and update cycle. Separating them keeps the application image smaller and avoids overcomplicating the assignment setup.

## Q020. When would a separate Ollama container make sense?

It can make sense when you want a fully containerized local stack. Even then, keeping it as a separate service is usually cleaner than folding it into the bot image.

## Q021. Which local ports matter most in this project?

Port `8000` matters for the web app and `11434` matters for Ollama. Those are the two numbers most likely to come up in local debugging.

## Q022. How do environment variables reach the container?

Compose reads `.env` through `env_file` and passes those values into the running service. The container then reads them through the app's settings loader.

## Q023. Should `.env` be committed with real secrets?

No. Secrets should stay local, while `.env.example` should document the variable names safely.

## Q024. How would I run the web app in Docker instead of the bot?

Change the service command from `python app.py` to `python web_app.py`. The image can support either entry point if the rest of the configuration fits.

## Q025. How can I override the container command temporarily?

Use a compose override, edit the compose file, or pass a one-off command depending on your workflow. The key idea is that the command is not hardwired into the image itself.

## Q026. Why are bind mounts useful during development?

They let the container see updated local files without baking every change into a new image. This speeds up iteration when changing data or configuration files.

## Q027. What is a common downside of bind mounts?

Permissions, path differences, and host-specific file behavior can be awkward. They are great for dev convenience but can be a source of local quirks.

## Q028. What if the container exits immediately after start?

Check the container logs first. The cause is often a startup exception, missing environment variable, or a command that terminated instead of staying alive.

## Q029. How do I inspect logs from a failed container startup?

Run `docker compose logs` or `docker compose logs -f`. Startup logs are usually the fastest path to the real error.

## Q030. How do I open a shell inside the running container?

Use `docker exec -it <container-name> sh` or the equivalent shell available in the image. This is useful for inspecting files or testing commands in the container context.

## Q031. How can I confirm Python is available inside the container?

Open a shell and run `python --version`. That quickly tells you whether the image was built with the expected Python runtime.

## Q032. How can I reindex the knowledge base from inside the container?

Run `python scripts/reindex.py` from inside the container if the script is present and the app files are mounted or copied into the image. That mirrors the host-side reindex command.

## Q033. Should the SQLite database live inside the image layer?

No. Runtime databases should live on a volume or bind mount so they survive rebuilds and are not baked into the image artifact.

## Q034. What if the host `data` folder does not exist yet?

Compose or Docker can create it when the bind mount starts, depending on the platform and exact setup. It is still better to know what should live there.

## Q035. Why rebuild after dependency changes?

Dependency changes affect the image contents. If you do not rebuild, the running container may still use the older installed package set.

## Q036. When is a restart enough without a rebuild?

A restart is enough when only environment variables or mounted runtime data changed and the image contents are still correct. Code or dependency changes usually need a rebuild.

## Q037. What should the Dockerfile usually do for an app like this?

It should copy the app metadata, install dependencies, copy the application code, and define the runtime command or entrypoint. The exact order affects build cache efficiency.

## Q038. Why do smaller images matter?

They build faster, ship fewer unnecessary files, and are easier to reason about. For a small assignment project, simplicity is usually better than maximal flexibility.

## Q039. What if the container cannot reach Gemini?

Check the API key, outbound network access, and whether the environment variable is present inside the container. The problem is usually configuration or network, not Docker itself.

## Q040. What does `localhost` mean inside a container?

Inside a container, `localhost` refers to the container itself, not the host machine. That matters when a service inside the container needs to reach a host-side dependency.

## Q041. How would a container reach a host-side Ollama server on Windows?

Use a host-access method such as `host.docker.internal` if needed. Plain `localhost` from inside the container will not reach a host process.

## Q042. Can I run just the bot service with Compose?

Yes. This compose file already defines only the bot service, so the setup is intentionally minimal.

## Q043. Can I run only the web app locally without Compose?

Yes. For quick debugging, running `python web_app.py` directly on the host is often simpler than going through Docker.

## Q044. Why is `--build` not required on every `docker compose up`?

If nothing affecting the image changed, Compose can reuse the existing image. Rebuilding every time adds unnecessary delay.

## Q045. What is the difference between image cache and runtime data?

Image cache speeds up builds, while runtime data is the mutable state produced by the app. Confusing the two leads to mistaken cleanup or stale-state debugging.

## Q046. Why is a `.dockerignore` often useful?

It keeps unnecessary files like virtual environments, caches, and logs out of the build context. That speeds builds and reduces accidental image bloat.

## Q047. Why should `.venv` stay out of the image context?

It is large, machine-specific, and unnecessary for image builds. Container images should install dependencies cleanly rather than copy a local virtual environment.

## Q048. Why should `data/omniquerybot.db` stay out of the image context?

The database is runtime state, not source code. It should be mounted or generated at runtime, not baked into the build artifact.

## Q049. How do I keep the Docker build context small?

Exclude logs, caches, virtual environments, databases, and other generated files. Smaller contexts lead to faster, cleaner builds.

## Q050. Why are logs not a substitute for tests?

Logs show what happened in one run, while tests verify expected behavior repeatedly. You need both for reliable development.

## Q051. What git command shows modified files?

Run `git status`. It is the quickest way to see changed, deleted, and untracked files.

## Q052. What git command stages files for commit?

Run `git add <path>` for specific files or `git add .` carefully if you truly want everything. Staging explicitly is usually safer.

## Q053. What git command creates a commit?

Run `git commit -m "your message"`. Clear, specific commit messages make future debugging and review easier.

## Q054. Why are small commits better than huge ones?

Small commits are easier to review, test, and revert mentally. They also make it clearer which change caused a regression.

## Q055. What does `git status` tell you beyond modified files?

It also shows untracked files, staged files, and branch state. That makes it a good first command before almost any git action.

## Q056. When should I use a branch?

Use a branch when the change is meaningful enough that you may want to isolate, review, or compare it later. It is especially helpful when experimenting.

## Q057. Why avoid force-push habits on shared work?

Force pushes rewrite history and can make collaboration painful. For a local assignment repo this may matter less, but the habit is still worth avoiding.

## Q058. Should generated logs be committed?

Usually no. Logs are generated artifacts and are better ignored unless there is a specific reason to preserve them as evidence outside the repo.

## Q059. Should lockfiles be committed when the project uses them?

Usually yes. A lockfile improves reproducibility and tells reviewers exactly which resolved dependency set was intended.

## Q060. Why should the README match the real commands?

The README is part of the setup contract with future users and reviewers. If it drifts from reality, onboarding gets harder and trust drops quickly.

## Q061. What is a safe pre-commit checklist?

Review `git status`, run tests, confirm startup still works, and make sure you are not accidentally committing logs or secrets. That catches many avoidable mistakes.

## Q062. How do I run tests in this repo?

Run `python -m pytest`. That is the main verification command documented in the project.

## Q063. What if tests fail after a doc change?

That usually means the change affected expected content or file layout. Document and retrieval changes can absolutely affect test outcomes in a RAG project.

## Q064. Should doc-only changes still be reindexed?

Yes. The runtime KB depends on indexed document content, so document edits need a fresh reindex even if no Python code changed.

## Q065. What operational events are worth logging?

Startup, reindex stats, request handling, provider failures, and major route decisions are all worth logging. These events give enough context to troubleshoot without drowning in noise.

## Q066. Why are startup stats like `files_seen` and `chunks_written` useful?

They show whether the knowledge base looks the way you think it does. A mismatch there often explains poor retrieval or stale answers.

## Q067. What request metrics matter most for this project?

Latency, HTTP status, source count, and whether the answer matched expectations all matter. Those metrics cover speed, stability, and grounding quality.

## Q068. How should a 100-question load test be judged?

Look at success rate, latency percentiles, answer quality, and refusal behavior for unsupported questions. A fast but hallucinating run is not actually a good result.

## Q069. What matters more in evaluation: speed or correctness?

Both matter, but correctness and honest fallback usually come first in a grounded assistant. A very fast wrong answer is still a bad answer.

## Q070. How should two model runs be compared fairly?

Use the same question set, same KB, same retrieval settings, and the same evaluation criteria. Otherwise the comparison becomes noisy and hard to trust.

## Q071. What is a sign of hallucination risk in results?

An answer that sounds confident but is unsupported by returned sources is a strong warning sign. Unsupported specificity is especially risky.

## Q072. What is a sign of a retrieval miss?

The answer may be vague, use the wrong file, or ignore an exact command that exists in the KB. Low-quality or zero-source responses are also clues.

## Q073. What suggests the provider is the bottleneck rather than retrieval?

Very high generation latency after retrieval completes is a clue. Logs that show fast retrieval but slow final-answer generation point to the model path.

## Q074. Why should exact commands be part of evaluation?

Users often ask operational questions that need literal commands, not paraphrases. A grounded bot should preserve exact commands when the KB includes them.

## Q075. Why test unsupported questions deliberately?

A grounded assistant must know when to refuse. Unsupported-question tests reveal whether the app hallucinates beyond the KB.

## Q076. How can I watch resource pressure during heavy local runs?

Use tools like `docker stats`, Task Manager, or other system monitors. Saturated CPU or memory can make local model behavior look worse than the code actually is.

## Q077. Why does CPU saturation matter so much for local models?

Local inference competes directly with everything else on the machine. When the CPU is overwhelmed, latency jumps and timeouts become more likely.

## Q078. How can I keep logs in both the terminal and a file?

Use a tee-style command in your shell so output is mirrored to both places. This is helpful when you want live visibility and a saved artifact.

## Q079. Why should only one Telegram polling process run at a time?

Telegram long polling is not designed for multiple competing pollers on the same bot token. Duplicate pollers usually trigger conflict errors.

## Q080. What causes the Telegram `getUpdates` conflict error?

It happens when another process is already polling the same bot. Stopping the older instance usually resolves it immediately.

## Q081. Why clean up old processes before rerunning services?

Old processes can hold ports, lock files, or keep polling Telegram. Cleanup removes hidden state that makes new runs behave unpredictably.

## Q082. Can Docker improve reproducibility for this project?

Yes, especially for dependency and runtime consistency. It does not solve every local model issue, but it can reduce environment drift.

## Q083. Can Docker also hide host-specific issues?

Yes. A container may isolate the app from some host quirks, but it can also hide host-service assumptions like `localhost` access.

## Q084. Why do local file mounts matter for SQLite?

SQLite stores state in a file, so bind mounts determine where that file persists. If the mount is wrong, state may vanish with the container.

## Q085. Why should the compose file stay simple for an assignment?

Simple infrastructure is easier to explain, review, and debug. Overengineering the deployment story rarely helps a local assignment bot.

## Q086. What if I only need the web app locally?

Run `python web_app.py` directly and skip Docker entirely. That is often the fastest path for frontend and API debugging.

## Q087. What if I only need the Telegram bot locally?

Run `python app.py` directly or use the compose bot service. There is no requirement to run both interfaces at once.

## Q088. What is the fastest local smoke test after a change?

Start the relevant interface, ask one known-good question, and verify the sources. If image handling changed, also upload one known-good image.

## Q089. Why should KB docs stay concise but rich?

Dense, heading-rich FAQs improve retrieval without scattering knowledge across too many tiny files. This is especially helpful for dense-only retrieval.

## Q090. Why can four bigger files outperform many tiny ones?

Fewer files reduce indexing clutter while still giving the splitter enough heading-based structure. Good headings matter more than raw file count.

## Q091. Why reindex immediately after deleting old docs?

The index still remembers deleted documents until reindex removes them. Reindex keeps SQLite aligned with the on-disk KB set.

## Q092. How are stale indexed documents removed?

The reindex step compares known disk paths to indexed document paths and deletes missing ones from the database. That keeps retrieval from serving deleted docs.

## Q093. Should query-cache hits be expected in repeated testing?

Yes. Repeated identical or normalized queries should reuse cached embeddings instead of recomputing them every time.

## Q094. Why should logs and large reports stay out of git?

They change often, add noise, and do not represent source code. Ignoring them keeps the repo focused and easier to review.

## Q095. What does `.gitignore` protect you from?

It keeps generated clutter like caches, logs, and local secrets from being committed by accident. Good ignore rules are basic repo hygiene.

## Q096. What if Windows refuses to delete an empty temp folder?

Treat it as a Windows permissions annoyance unless it actively blocks work. If the folder is ignored and empty, it is mostly cosmetic.

## Q097. How should I think about locked but empty temp folders?

They are not source code and usually do not affect runtime behavior. Ignore them, avoid committing them, and do not waste disproportionate time on them.

## Q098. What is the minimal Docker, git, and test checklist?

Make sure the service starts, `git status` looks clean enough, and `python -m pytest` passes. That covers the basics without overcomplicating the workflow.

## Q099. What is a minimal release-readiness checklist for this repo?

Confirm setup commands are correct, the KB is indexed, the bot and web app start, and the tests pass. Those are the essentials for an assignment-grade handoff.

## Q100. What is the best short operations checklist?

Keep the repo clean, keep secrets out of git, rebuild or restart deliberately, reindex after KB changes, and verify with at least one smoke test plus `pytest`. That is enough discipline for a small but serious local app.
