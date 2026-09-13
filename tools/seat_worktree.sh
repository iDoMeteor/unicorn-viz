#!/usr/bin/env bash
# Create or refresh a per-seat git worktree of unicorn-viz.
#
#   tools/seat_worktree.sh <seat-name>        e.g. core, mixer, media, videos
#   tools/seat_worktree.sh --list
#
# Why: every agent seat used to work in the one shared checkout.  pre-commit
# stashes the tree's unstaged changes while it runs, so one seat's hook
# would stash -- and on a collision lose -- another seat's uncommitted
# work, revert config.toml under a live app, and fail on files the
# committer never touched (2026-09-13: three lost commits, a stashed batch,
# a reverted config and two collided live runs in one afternoon).  A
# worktree per seat gives each its own index and working tree; hooks then
# only ever see the committing seat's files.
#
# What a seat gets:
#   ~/Repos/unicorn-viz-seats/<name>   a worktree on branch seat/<name>
#   drop-ins/*                         every submodule checked out at the
#                                      pinned commit, on its own branch,
#                                      cloned from the main repo's local
#                                      object store (no network), origin
#                                      pointing at GitHub as usual
#   .venv                              symlink to the main checkout's venv
#                                      (the hooks run .venv/bin/python)
#   Claude memory                      the seat's memory directory is a
#                                      symlink to the shared one, so a
#                                      session started in the seat keeps
#                                      every note
#
# Landing work from a seat (no rebase, no force-push, ever):
#   git push origin HEAD:master            # fast-forward master on origin
#   # rejected as non-fast-forward?  someone landed first:
#   git fetch origin && git merge origin/master   # a merge commit is fine
#   git push origin HEAD:master
# Drop-in work is unchanged: commit + push in drop-ins/<name> first, then
# the pointer bump on the seat branch, then push as above.
#
# The app itself keeps running from the main checkout -- runtime/, logs/
# and the session data live there.  The main checkout stays on master and
# only ever pulls (git pull --ff-only).
set -euo pipefail

if [ "${1:-}" = "" ] || [ "$1" = "-h" ] || [ "$1" = "--help" ]; then
    sed -n '2,40p' "$0" | sed 's/^# \{0,1\}//'
    exit 0
fi

# The main checkout is the one whose .git holds the worktrees.
COMMON="$(git rev-parse --git-common-dir 2>/dev/null || true)"
case "$COMMON" in
    /*) ;;
    *) COMMON="$(cd "$(git rev-parse --show-toplevel)" && cd "$COMMON" && pwd)" ;;
esac
MAIN="$(dirname "$COMMON")"
SEATS_DIR="${UNICORNVIZ_SEATS_DIR:-$(dirname "$MAIN")/unicorn-viz-seats}"

if [ "$1" = "--list" ]; then
    git -C "$MAIN" worktree list
    exit 0
fi

name="$1"
case "$name" in
    */*|*' '*|'') echo "seat name must be a single word (got '$name')" >&2; exit 2 ;;
esac
T="$SEATS_DIR/$name"
BR="seat/$name"
mkdir -p "$SEATS_DIR"

echo "== seat '$name' -> $T (branch $BR)"
git -C "$MAIN" fetch -q origin

if [ ! -d "$T" ]; then
    if git -C "$MAIN" show-ref -q --verify "refs/heads/$BR"; then
        git -C "$MAIN" worktree add -q "$T" "$BR"
    else
        git -C "$MAIN" worktree add -q -b "$BR" "$T" origin/master
    fi
    echo "   worktree created at $(git -C "$T" rev-parse --short HEAD)"
else
    echo "   worktree exists at $(git -C "$T" rev-parse --short HEAD); refreshing submodules"
fi

# Submodules: a real clone per seat (each seat commits in its own drop-in
# checkouts), with objects shared from the main checkout's module store so
# it takes seconds and no network.
git -C "$T" config -f .gitmodules --get-regexp 'submodule\..*\.path' | awk '{print $2}' | while read -r path; do
    sha="$(git -C "$T" ls-tree HEAD -- "$path" | awk '{print $3}')"
    [ -n "$sha" ] || continue
    # .gitmodules is not always complete (some effects drop-ins carry no
    # url there); the main checkout's own remote is the fallback.
    url="$(git -C "$T" config -f .gitmodules "submodule.$path.url" 2>/dev/null || true)"
    [ -n "$url" ] || url="$(git -C "$MAIN/$path" remote get-url origin 2>/dev/null || true)"
    store="$COMMON/modules/$path"
    fresh=0
    if [ ! -e "$T/$path/.git" ]; then
        fresh=1
        if [ ! -d "$store" ]; then
            [ -n "$url" ] || { echo "   $path: no local store and no url; skipped" >&2; continue; }
            echo "   $path: no local store at $store, cloning from origin"
            rm -rf "$T/$path"
            git clone -q --no-checkout "$url" "$T/$path"
        else
            rm -rf "$T/$path"
            git clone -q --shared --no-checkout "$store" "$T/$path"
            [ -n "$url" ] && git -C "$T/$path" remote set-url origin "$url"
        fi
    fi
    # A clone made with --no-checkout has an index and an empty tree; a seat
    # that was provisioned by an earlier run of this script may also be in
    # that state.  Either way there is no local work to protect yet.
    if [ "$(ls -A "$T/$path" | grep -vc '^\.git$')" = "0" ]; then
        fresh=1
    fi
    # The branch the main checkout has this drop-in on (main or master);
    # fall back to the remote's default.  Never leave a seat detached.
    branch="$(git -C "$MAIN/$path" symbolic-ref -q --short HEAD 2>/dev/null || true)"
    if [ -z "$branch" ]; then
        branch="$(git -C "$T/$path" symbolic-ref -q --short refs/remotes/origin/HEAD 2>/dev/null | sed 's#^origin/##' || true)"
    fi
    [ -n "$branch" ] || branch=main
    if [ "$fresh" = "1" ]; then
        # Fresh clone (or an empty tree from a --no-checkout clone): put the
        # branch at the pinned commit and materialize the files.  Safe only
        # here -- a seat with work in progress is never hard-reset.
        git -C "$T/$path" checkout -q -B "$branch" "$sha"
        git -C "$T/$path" reset -q --hard "$sha"
    elif [ "$(git -C "$T/$path" rev-parse HEAD 2>/dev/null || true)" != "$sha" ]; then
        git -C "$T/$path" checkout -q -B "$branch" "$sha" || \
            echo "   $path: could not move to $sha (local changes?); left as is" >&2
    fi
    git -C "$T/$path" branch -q --set-upstream-to="origin/$branch" "$branch" 2>/dev/null || true
done
echo "   submodules: $(git -C "$T" submodule status 2>/dev/null | grep -c '^ ' || true) at their pinned commits"

# Shared virtualenv (hooks and tools call .venv/bin/python by relative path).
if [ -d "$MAIN/.venv" ] && [ ! -e "$T/.venv" ]; then
    ln -s "$MAIN/.venv" "$T/.venv"
fi
echo "   .venv -> $MAIN/.venv"

# Shared Claude memory for a session started in this seat.
slug="$(printf '%s' "$T" | sed 's#/#-#g')"
shared="$HOME/.claude/projects/$(printf '%s' "$MAIN" | sed 's#/#-#g')/memory"
if [ -d "$shared" ]; then
    mkdir -p "$HOME/.claude/projects/$slug"
    if [ ! -e "$HOME/.claude/projects/$slug/memory" ]; then
        ln -s "$shared" "$HOME/.claude/projects/$slug/memory"
    fi
    echo "   memory -> $shared"
fi

cat <<MSG

Ready.  Start the seat's session in:  $T
Land work with:                       git push origin HEAD:master
Catch up with:                        git fetch origin && git merge origin/master
MSG
