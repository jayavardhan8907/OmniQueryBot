# Docker Basics FAQ

## Why include Docker for this assignment?

Docker is optional for the local demo, but it gives reviewers a second path to run the bot without manually setting up the Python environment. That makes the submission look cleaner and more production-aware without adding too much complexity.

## What should Docker Compose run here?

Docker Compose should run a single bot service based on Python 3.11. It should mount the repository into the container, read environment variables from `.env`, and persist the SQLite database under the `data/` directory so indexing results survive container restarts.

## Why not use webhooks in Docker?

The assignment only requires a bot that works locally. Long polling is simpler than configuring a public HTTPS endpoint, certificates, reverse proxying, or tunneling software. It also keeps the README shorter and easier to follow.

## What should be documented for Docker users?

The README should explain how to build and start the service with `docker compose up --build`, how to stop it, and how to rebuild the knowledge base if the sample documents change. Mention that the first startup may take longer because the embedding model has to download.
