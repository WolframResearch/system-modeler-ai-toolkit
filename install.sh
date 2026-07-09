#!/usr/bin/env bash
#
# Install the System Modeler agent skills into a Claude Code skills directory.
#
# This links (or copies) BOTH the per-skill directories AND the shared scripts/
# folder into the target. Linking the skills without scripts/ is the #1 cause of
# "wsm_run.py not found": every SKILL.md refers to the launcher as
# ../scripts/wsm_run.py, so scripts/ must sit alongside the skill dirs.
#
# An existing entry in the target is replaced only when it is a symlink that
# points back into this repo (i.e. a previous install by this script). Anything
# else is left untouched with a warning; pass --force to replace it anyway.
#
# Usage:
#   ./install.sh                       # symlink into ~/.claude/skills
#   ./install.sh --target DIR          # symlink into a custom skills dir
#   ./install.sh --copy                # copy instead of symlink
#   ./install.sh --force               # also replace entries not from this repo
#   ./install.sh --target DIR --copy
#
set -euo pipefail

# pwd -P (physical) so a repo reached via a symlinked path still compares equal
# to a physically-resolved target in the self-install guard below.
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
TARGET="${HOME}/.claude/skills"
MODE="link"
FORCE=0

while [ $# -gt 0 ]; do
  case "$1" in
    --target)
      if [ $# -lt 2 ] || [ -z "$2" ]; then
        echo "ERROR: --target requires a directory argument." >&2
        exit 2
      fi
      TARGET="$2"; shift 2 ;;
    --copy)   MODE="copy"; shift ;;
    --force)  FORCE=1; shift ;;
    -h|--help)
      sed -n '2,20p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'
      exit 0 ;;
    *) echo "Unknown argument: $1" >&2; exit 2 ;;
  esac
done

# The skill directories (each holds a SKILL.md) plus the shared scripts folder.
# Discover the skill dirs from disk (any dir with a SKILL.md) so new skills are
# picked up automatically and this list can't drift from what's in the repo.
ITEMS=()
for skill_md in "$REPO_ROOT"/*/SKILL.md; do
  [ -e "$skill_md" ] || continue   # no matches -> the literal glob; skip it
  ITEMS+=("$(basename "$(dirname "$skill_md")")")
done
ITEMS+=(scripts)

mkdir -p "$TARGET"
# Refuse to install into the repo itself: dst would BE src, and replacing an
# "existing entry" below would delete the real skill sources.
if [ "$(cd "$TARGET" && pwd -P)" = "$REPO_ROOT" ]; then
  echo "ERROR: target ($TARGET) is the repo folder itself; choose another --target." >&2
  exit 2
fi
echo "Installing skills from $REPO_ROOT"
echo "                  into $TARGET   (mode: $MODE)"
echo

# Is $1 a symlink we may replace silently? Yes if it resolves back into this
# repo (a previous install), or if it is dangling (removing it loses nothing —
# typically a leftover link after the repo was moved).
owned_by_repo() {
  local link="$1" dest
  [ -L "$link" ] || return 1
  [ -e "$link" ] || return 0        # dangling symlink
  dest="$(cd -P "$link" 2>/dev/null && pwd)" || return 1
  case "$dest" in
    "$REPO_ROOT"|"$REPO_ROOT"/*) return 0 ;;
  esac
  return 1
}

tmp=""
trap '[ -n "$tmp" ] && rm -rf "$tmp" || true' EXIT

for item in "${ITEMS[@]}"; do
  src="$REPO_ROOT/$item"
  dst="$TARGET/$item"
  if [ ! -e "$src" ]; then
    echo "  skip  $item  (not present in repo)"
    continue
  fi
  # Replace an existing entry only when it is ours (a symlink back into this
  # repo) — never silently delete something the user put there themselves.
  if [ -e "$dst" ] || [ -L "$dst" ]; then
    if owned_by_repo "$dst"; then
      : # our own link from a previous install; replace silently
    elif [ "$FORCE" -eq 1 ]; then
      echo "  WARNING: replacing $dst (not installed from this repo) because of --force" >&2
    else
      echo "  WARNING: $dst exists and was not installed from this repo; skipping — remove it manually or re-run with --force" >&2
      continue
    fi
  fi
  if [ "$MODE" = "copy" ]; then
    # Stage the copy under a temp name in the target dir, then swap it into
    # place, so a mid-copy failure never leaves the user with neither the old
    # nor the new entry.
    tmp="$TARGET/.$item.installing.$$"
    rm -rf "$tmp"
    if ! cp -R "$src" "$tmp"; then
      rm -rf "$tmp"
      echo "ERROR: failed to copy $item into $TARGET" >&2
      exit 1
    fi
    rm -rf "$dst"
    mv "$tmp" "$dst"
    tmp=""
    echo "  copy  $item"
  else
    rm -rf "$dst"
    ln -s "$src" "$dst"
    echo "  link  $item -> $src"
  fi
done

echo
echo "Done. The launcher is reachable from each skill as ../scripts/wsm_run.py"
echo "Verify with:  python3 \"$TARGET/scripts/wsm_run.py\" --mode info"
