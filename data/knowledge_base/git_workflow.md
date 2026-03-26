# Git Workflow FAQ

## What is the recommended branch flow?

Keep the `main` branch stable and create a short-lived feature branch for each task. Commit small logical checkpoints instead of one large commit at the end. This makes debugging, reviewing, and reverting much easier.

## How should commits be structured?

Each commit should represent one coherent change such as "add retrieval service" or "write README setup instructions". Avoid mixing unrelated refactors with feature work in the same commit. If a change touches configuration and code, explain both in the commit message body.

## How do I inspect the current repository state?

Run `git status --short` to check modified and untracked files. Use `git diff` to inspect unstaged edits and `git diff --cached` to inspect staged changes. Review the output before committing so accidental file changes do not sneak into the assignment submission.

## What should I avoid in a shared repository?

Avoid destructive commands such as `git reset --hard` unless you are completely sure the working tree is disposable. In collaborative environments, it is safer to create a backup branch or stash than to remove history or local edits.
