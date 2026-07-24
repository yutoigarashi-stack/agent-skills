---
name: git-pull-with-stash
description: Safely update the current Git branch while preserving local tracked changes, staged state, and untracked files. Use when the user asks to stash current work, pull remote changes, and restore or pop the stash; asks to pull without losing unfinished changes; or describes the repeated stash-pull-unstash workflow.
---

# Pull with stash

Update the current branch with fast-forward-only semantics, then restore the
user's local work exactly enough to preserve its staged and unstaged state.
Use standard Git commands directly; do not create a helper script.

## Workflow

1. Inspect the repository before changing it.
   - Resolve the intended worktree with `git rev-parse --show-toplevel`.
   - Show `git status --short --branch`.
   - Require a named current branch and configured upstream.
   - Stop before stashing when a merge, rebase, cherry-pick, revert, or bisect
     is in progress.
   - Stop when a submodule contains local changes; the parent repository's
     stash does not safely preserve those changes.
2. Record recovery information.
   - Record the current `HEAD` commit.
   - Record `git stash list --format='%H %gd %gs'` so pre-existing stashes can
     be distinguished from the stash created by this workflow.
   - Inspect tracked and untracked changes with
     `git status --porcelain --untracked-files=all`.
3. Pull immediately when there is nothing to stash.
   - Keep ignored files in place.
   - Run `git pull --ff-only`.
   - Report the resulting branch and commit; do not create or delete a stash.
4. Stash local work when changes exist.
   - By default, run `git stash push --include-untracked --message
     "git-pull-with-stash: <branch> <timestamp>"`.
   - Use `--all` instead of `--include-untracked` only when the user explicitly
     asks to include ignored files. Never infer permission to stash ignored
     files.
   - Capture the new stash commit with `git rev-parse refs/stash`. Verify that
     it is new and that the worktree is clean apart from intentionally excluded
     ignored files. If verification fails, restore the new stash when safe and
     stop.
5. Update the branch with `git pull --ff-only`.
   - Never replace this with an automatic merge, rebase, reset, or force
     operation.
   - If pull fails, compare `HEAD` and the worktree with the recorded state. If
     `HEAD` is unchanged and the worktree is clean, restore the exact new stash
     as described below. Otherwise keep the stash and stop without destructive
     cleanup.
6. Restore the exact stash with `git stash apply --index <stash-commit>`.
   - Use the recorded stash commit, not an assumed `stash@{0}`.
   - If applying fails or creates conflicts, keep the stash, show
     `git status --short --branch`, and report the stash commit. Do not retry
     without `--index`, drop the stash, or discard conflict state.
   - If applying succeeds, find the stash-list entry whose commit matches the
     recorded commit and drop only that entry with `git stash drop <stash-ref>`.
     If the matching entry cannot be identified, leave it in place and report
     the duplicate recovery copy.
7. Verify and report the result.
   - Show the final branch, `HEAD`, and short status.
   - Confirm whether pull succeeded, whether staged/untracked work was
     restored, and whether the workflow's stash was dropped or retained.

## Safety rules

- Preserve all stashes that existed before this workflow.
- Prefer a recoverable duplicate stash over deleting the wrong stash.
- Do not run `git stash pop`, `git clean`, `git reset`, `git restore`, or a
  force operation as part of this workflow.
- Do not resolve stash-application conflicts unless the user separately asks
  for conflict resolution.
