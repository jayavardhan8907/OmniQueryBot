# Python, Windows, and Environment FAQ

This file consolidates environment guidance from official Python and `uv` documentation plus the exact commands used in this repository.

## Q001. Why use a virtual environment?

A virtual environment isolates one project's packages from the rest of the machine. That makes setup reproducible and prevents dependency conflicts between repositories.

## Q002. Which Python version is the safest default for this project?

Python 3.11 is the safest default here. It is widely supported by machine-learning and embedding packages and matches the commands already used in this repository.

## Q003. Why prefer Python 3.11 over a brand-new interpreter release?

Very new Python versions can expose package build and wheel-availability issues first. Choosing 3.11 usually reduces setup friction on Windows for local AI tooling.

## Q004. How do I create the environment on Windows?

On Windows, create the environment by running `py -3.11 -m venv .venv` from the project root. That exact command creates the local Python virtual environment inside the `.venv` folder for this project.

## Q005. Why create `.venv` in the repository root?

A root-level `.venv` is easy for humans and editors to detect. It also keeps the environment clearly tied to this repository instead of some shared global location.

## Q006. How do I activate the environment in PowerShell?

In PowerShell on Windows, activate the environment with `.\.venv\Scripts\activate`. When activation works, the prompt usually starts with `(.venv)`.

## Q007. How do I activate the environment in Command Prompt?

Run `.\.venv\Scripts\activate.bat`. The same environment is used; only the shell-specific activation script changes.

## Q008. How do I deactivate the environment?

Run `deactivate`. That leaves the virtual environment on disk and only exits it for the current shell session.

## Q009. How do I verify the correct interpreter is active?

Run `python --version` and confirm it shows Python 3.11.x. Then run `python -c "import sys; print(sys.executable)"` and make sure the path points into `.venv`.

## Q010. Why is `where python` useful on Windows?

`where python` shows which executable paths Windows would use. The first result should usually come from `.venv\Scripts` when the environment is active.

## Q011. What should I do if PowerShell says script execution is disabled?

If PowerShell says script execution is disabled, run `Set-ExecutionPolicy -Scope Process RemoteSigned` in that terminal and then activate again. This is a session-only change and is safer than a machine-wide policy change.

## Q012. Why use `-Scope Process` for execution policy?

It limits the change to the current shell session. That lowers risk and avoids permanently changing system-wide script rules just to activate one local environment.

## Q013. Should I use `uv` or plain `pip` here?

Either can work, but `uv` is usually better for fast, reproducible project syncs. Plain `pip` is still a valid fallback when you want a simpler or more familiar workflow.

## Q014. What does `uv sync` do?

`uv sync` aligns the local environment with the project's declared dependencies and lockfile. It is the fastest way to make the environment match the repository state.

## Q015. What does an editable install do?

An editable install makes local source code changes immediately visible to the environment. That is helpful during development because you do not need to reinstall after every code edit.

## Q016. When is `uv pip install -r requirements.txt` useful?

It is useful when you want a requirements-file workflow while still using `uv` as the installer. In this repo, `requirements.txt` is a lightweight helper that installs the project and dev extras.

## Q017. When should I recreate `.venv`?

Recreate it when the Python version changes, compiled packages break, imports drift badly from the lockfile, or debugging the current environment would take longer than rebuilding it.

## Q018. What is the safest rebuild sequence?

Delete `.venv`, run `py -3.11 -m venv .venv`, activate it, and reinstall dependencies. That removes interpreter drift and broken local package state in one pass.

## Q019. Why avoid installing project packages globally?

Global installs make it easy for one project to break another. They also make assignment review harder because another machine may not have the same global package mix.

## Q020. Should `.venv` be committed to git?

No. Virtual environments are machine-specific build artifacts and should be recreated locally instead of versioned.

## Q021. What does `.python-version` do in a `uv` workflow?

It records the preferred interpreter version for the project. Tools like `uv` can use it when deciding which Python version to create the environment with.

## Q022. Why is `uv.lock` valuable?

It records the exact resolved dependency set. That makes installs more reproducible across machines and helps teams avoid subtle version drift.

## Q023. Should `uv.lock` be edited by hand?

No. It is a generated lockfile and should normally be changed through `uv` commands rather than manual edits.

## Q024. What is `pyproject.toml` for?

It is the main project metadata and dependency file. It defines package requirements, project metadata, and tool configuration.

## Q025. Should multiple repositories share the same virtual environment?

Usually no. Shared environments make dependencies bleed across projects and remove the main reproducibility benefit of a repo-local environment.

## Q026. Why is the Windows `py` launcher helpful?

It lets you target a specific installed interpreter such as `py -3.11`. That is safer than assuming `python` on `PATH` points to the version you want.

## Q027. How can I see installed Python interpreters on Windows?

Run `py -0p`. It lists registered interpreters and their filesystem paths.

## Q028. What if `py` is not found?

Use the full Python path if needed or install Python from the official Windows installer and ensure the launcher is included. After that, retry the setup command.

## Q029. What command installs dependencies after activation?

Use `uv sync` if you are following the `uv` workflow. If you want the helper file path, run `uv pip install -r requirements.txt`.

## Q030. How should I update dependencies safely?

Use the package manager to update declared dependencies, regenerate the lockfile, and retest the app. Random manual installs inside `.venv` make reproduction harder.

## Q031. How do I add a dependency with `uv`?

Run `uv add <package-name>`. That updates project metadata and keeps the environment and lockfile aligned.

## Q032. How do I remove a dependency with `uv`?

Run `uv remove <package-name>`. That removes the declaration and lets `uv` update the lockfile cleanly.

## Q033. How can I confirm a package is installed?

Run `python -m pip show <package-name>` or `uv pip show <package-name>`. You can also test an import with `python -c "import package_name"`.

## Q034. Why use `python -m pip` instead of plain `pip`?

It ties `pip` to the currently selected interpreter. That reduces the chance of installing into the wrong Python installation.

## Q035. What if `pip` installed packages into global Python by mistake?

Activate the correct environment and reinstall there. If the project still behaves strangely, rebuild `.venv` to remove ambiguity.

## Q036. What exactly does `python -m venv` create?

It creates an isolated Python environment with its own interpreter, site-packages, and activation scripts. It does not copy every global package into the new environment.

## Q037. What files normally live inside `.venv`?

You will usually see interpreter binaries, site-packages, scripts, and a `pyvenv.cfg` file. The exact layout varies slightly by platform.

## Q038. Can I rename the environment folder?

Yes, but `.venv` is the most common and easiest name for editors and tooling to detect automatically. Sticking with that name reduces surprises.

## Q039. Is activation required to use the environment?

No. Activation is a convenience layer. You can always call the interpreter directly, such as `.\.venv\Scripts\python.exe app.py`.

## Q040. Can I run commands without activation?

Yes, by using explicit interpreter paths or `uv run`. Activation just makes command entry shorter and less error-prone.

## Q041. Which environment file matters for runtime configuration?

`.env` matters because the app loads it for provider, model, database, and path settings. It is separate from the Python package environment itself.

## Q042. Should `.env` be committed?

No. It often contains secrets such as API keys and tokens. Keep it local and provide a safe example file instead.

## Q043. What is the difference between `.env` and `.env.example`?

`.env` is the real local configuration. `.env.example` is a safe template that documents required variables without including secrets.

## Q044. Which text-model variables matter most?

`TEXT_PROVIDER`, `TEXT_MODEL`, and `GEMINI_MODEL` matter most for text generation. They decide whether the app uses Ollama or Gemini and which model name is requested.

## Q045. Which vision variables matter most?

`VISION_PROVIDER`, `VISION_MODEL`, and `GEMINI_MODEL` matter most for image generation. They control which provider handles the image caption path.

## Q046. What is `OLLAMA_BASE_URL` for?

It tells the app where the local Ollama server is listening, such as `http://localhost:11434`. Without the correct base URL, Ollama calls will fail.

## Q047. What does `GEMINI_MODEL` control?

It selects the Gemini model name used by the Gemini provider path. The current project uses that variable for both text and image flows when Gemini is enabled.

## Q048. What does `RAG_MAX_OUTPUT_TOKENS` control?

It controls the answer budget for grounded RAG responses. A larger value allows more complete answers but can increase latency and cost.

## Q049. How can I verify that `.env` values are loaded?

Start the app and check logs or the `/api/config` endpoint for the non-secret settings that are exposed. If those match expectations, the environment file is likely loading correctly.

## Q050. What is the safest startup checklist?

Activate `.venv`, confirm Python 3.11, confirm `.env` exists, install dependencies, and only then start the app. That prevents many setup mistakes from being misdiagnosed as app bugs.

## Q051. Why do wheels matter on Windows?

Prebuilt wheels avoid local compilation and make setup faster. When wheels are unavailable for a specific Python version, install friction rises sharply.

## Q052. Why do compiled packages often fail first on brand-new Python versions?

Compiled dependencies need compatible wheels or build toolchains. New interpreter releases can temporarily outrun the package ecosystem.

## Q053. What should I do if a package build fails?

Check the Python version first, then retry in a clean 3.11 environment. Many failures disappear when the interpreter and wheel availability are aligned.

## Q054. Do I need an administrator shell for normal setup?

Usually no. A normal user shell is preferred because the project environment is local to the repository and should not require system-wide changes.

## Q055. Can I use `uv run` instead of activating `.venv`?

Yes. `uv run` can execute commands inside the project environment without manual activation, which is useful for quick one-off commands.

## Q056. What would `uv run python app.py` do?

It would start the Telegram bot using the project environment that `uv` manages. That avoids ambiguity about which interpreter is used.

## Q057. What command starts the local web app?

Run `python web_app.py` from the project root, or call the venv interpreter directly. That starts the FastAPI-based local tester.

## Q058. What command starts the Telegram bot?

Run `python app.py` from the project root, or `.\.venv\Scripts\python.exe .\app.py`. Both use the same shared core services when the environment is configured correctly.

## Q059. What command reindexes the knowledge base?

Run `python scripts\reindex.py`. Reindex after changing KB documents so the SQLite-backed chunk store is updated.

## Q060. Should I reindex after editing knowledge-base files?

Yes. The retrieval layer depends on indexed chunks stored in SQLite, so document edits are not live until reindex completes.

## Q061. What if I get `ModuleNotFoundError`?

The wrong interpreter is usually active or dependencies are missing from `.venv`. Confirm `sys.executable` and reinstall into the correct environment if needed.

## Q062. What if my editor is using the wrong interpreter?

Point the editor to `.venv\Scripts\python.exe`. Otherwise linting, tests, and runs may all target a different Python installation from the one you expect.

## Q063. Why should the editor and terminal use the same interpreter?

Using different interpreters creates confusing "works in one place but not another" failures. Aligning both removes a whole class of environment bugs.

## Q064. Which file is the real dependency source of truth?

`pyproject.toml` is the real source of truth for declared dependencies in this repo. `requirements.txt` is mainly a convenience wrapper for installation.

## Q065. Why keep `requirements.txt` if `pyproject.toml` exists?

It offers a simple install entry point and can be friendlier for reviewers who expect a requirements-based command. It does not replace the project metadata file.

## Q066. Can the project still work with a pure pip workflow?

Yes, if dependencies are installed correctly into `.venv`. The repo is easiest to reproduce with `uv`, but the core Python app does not fundamentally require it.

## Q067. What if `where python` shows several executables?

That is normal on Windows, but the first one in the list matters most. When `.venv` is active, the first result should usually be the project interpreter.

## Q068. How do I confirm `.venv\Scripts` is first on the active shell path?

Check `where python` and `where pip`. If both resolve to `.venv\Scripts` first, the shell is using the project environment correctly.

## Q069. What if activation worked but the prompt did not change?

The prompt decoration is helpful but not authoritative. Verify the interpreter path directly before assuming activation failed.

## Q070. Can the environment break after a Python upgrade?

Yes. Upgrading the base interpreter can invalidate compiled packages or leave the environment in a mismatched state, so rebuilding is often safest.

## Q071. Should I delete individual packages inside `site-packages` by hand?

Usually no. Rebuilding the whole environment is cleaner, faster, and less error-prone than partial manual surgery.

## Q072. Why is `Set-ExecutionPolicy -Scope Process RemoteSigned` a common Windows fix?

It temporarily permits the local activation script without permanently opening broader script execution permissions. That makes it a practical compromise for development.

## Q073. Is a session-only execution-policy change safer than a machine-wide one?

Yes. It affects only the current shell and disappears when the shell closes.

## Q074. Does PowerShell 7 activate the environment differently?

The activation command is still `.\.venv\Scripts\activate`. The main differences are shell behavior and configuration, not the path to the activation script.

## Q075. Why do Windows paths use backslashes in commands here?

Backslashes are standard Windows path separators and make the instructions feel native for local setup. The repository uses Windows-focused commands in several places for consistency.

## Q076. Why prefer repo-root-relative commands?

They make the instructions copy-paste friendly and reduce the risk of running the right command from the wrong directory. That is especially useful in assignment reviews.

## Q077. What if `.venv` does not exist yet?

Create it first with `py -3.11 -m venv .venv`. Activation and installs depend on that folder being present.

## Q078. Can I share `.venv` with a teammate by zipping it?

That is a bad default. Local environments are platform- and machine-specific and are better recreated from the repo configuration.

## Q079. What if the repository path contains spaces?

The setup can still work, but quoting command arguments becomes more important. Simpler paths usually reduce avoidable Windows shell issues.

## Q080. Can forward slashes work in some Python-related commands on Windows?

Sometimes yes, but not every Windows tool handles them consistently. The safest instructions for this repo use standard Windows-style paths.

## Q081. What if `uv` is not installed?

Install `uv` first or fall back to a plain pip workflow. The project can still run, but `uv` is the smoother path when available.

## Q082. How is `uv` usually installed?

Use the official Astral installation instructions from the `uv` docs. The exact install method can vary by platform and preference.

## Q083. Can `uv` itself be installed with `pip`?

It can be in some setups, but the official installation instructions are the safer reference. Following the upstream docs reduces version and path surprises.

## Q084. Why should I sync after pulling fresh changes?

New commits may change dependencies, lockfiles, or runtime expectations. Syncing after pull keeps your local environment aligned with the repository state.

## Q085. What if the lockfile is missing?

The project may still install from declared dependencies, but reproducibility gets weaker. If the workflow expects `uv.lock`, regenerate it through `uv` rather than inventing it by hand.

## Q086. Do I need to delete the SQLite database when rebuilding `.venv`?

Not usually. The database is separate from the Python environment and only needs to be rebuilt when its own contents are stale or corrupted.

## Q087. What if `.env` is missing entirely?

Create it from the example template and fill in the required variables. Without it, provider selection and runtime configuration may fail.

## Q088. Should secrets ever live in `README.md`?

No. Documentation should explain required variables, but real secrets should stay in local environment files or secure secret stores.

## Q089. Why do package import names sometimes differ from package install names?

Distribution names and import paths are not always identical in Python. If an import fails, check the package docs rather than assuming the names match exactly.

## Q090. Why is `python -c "import sys; print(sys.executable)"` such a good sanity check?

It cuts through shell prompt assumptions and shows the exact interpreter in use. That makes it one of the fastest environment diagnostics on Windows.

## Q091. What if `python --version` and `py -3.11` point to different interpreters?

That means your default `python` command is not the same interpreter targeted by the launcher. Build and activate `.venv` explicitly so the active shell becomes unambiguous.

## Q092. Should the bot and the web app share the same environment?

Yes. They use the same project code and dependencies, so a shared repo-local environment is the simplest and most reliable setup.

## Q093. Why restart the app after changing `.env`?

Configuration values from `.env` are read at startup. A running process will not automatically pick up new settings unless it is restarted.

## Q094. What if a command returns `Access is denied` on Windows?

Check whether the target file is locked by another process, whether the shell has enough rights, and whether antivirus or indexing tools are interfering. Empty temp folders with broken ACLs are a separate Windows annoyance and can often just be ignored.

## Q095. What if antivirus blocks scripts or executables?

Confirm the files are local project artifacts and retry after a clean reinstall if necessary. Security tools can occasionally interfere with local development shells and generated executables.

## Q096. Should model downloads live inside `.venv`?

Usually no. Large model files and caches are better treated as runtime data, not as part of the Python package environment itself.

## Q097. Can one `.venv` support both Telegram and FastAPI flows?

Yes. The same dependency set supports both interfaces because they share the same underlying services and code modules.

## Q098. What is the minimal clean install sequence for this repo?

Create `.venv`, activate it, install dependencies, create `.env`, and reindex the knowledge base. After that, start either the web app or the Telegram bot.

## Q099. What is the fastest reliable reset sequence?

Delete `.venv`, recreate it with Python 3.11, reinstall dependencies, confirm `.env`, and reindex the KB. That clears most setup drift with minimal guesswork.

## Q100. What is the best short checklist before running the app?

Make sure `.venv` is active, Python 3.11 is selected, dependencies are installed, `.env` exists, and the KB has been reindexed. If those five checks pass, most startup problems are already ruled out.
