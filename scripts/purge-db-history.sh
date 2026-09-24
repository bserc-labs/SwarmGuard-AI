#!/bin/sh
# Remove every committed SQLite database from git history. PREPARES, VERIFIES
# AND STOPS: it never pushes.
#
#   scripts/purge-db-history.sh <source> <workdir>
#
#   source    what to rewrite: the GitHub URL, or a local path for a rehearsal
#   workdir   a directory that must not exist yet; the rewritten mirror goes here
#
# Needs git-filter-repo (pip install git-filter-repo) and, to name the accounts
# whose password hashes were exposed, sqlite3.
#
# Why this is a script and not a pull request. `swarmguard.db` was committed,
# modified and deleted across a dozen commits, and `swarmguard 2.db` and
# `swarmguard 3.db` once more. The files are untracked today, but every clone
# still carries the blobs, and with them the users table: password hashes for
# the accounts listed at the end of the run. Removing them means rewriting
# every commit after the first one, which changes every commit id, which means
# a force-push and every existing clone and fork being thrown away. That is the
# repository owner's decision and a moment everyone agrees on.
#
# What to do with the result, in this order:
#   1. Rotate: every account the run names gets a new password, wherever that
#      account exists. Rewriting history does not un-leak a hash that has
#      already been cloned; rotation is what actually closes it.
#   2. Tell everyone with a clone that one is coming, then push from <workdir>
#      with the commands printed at the end.
#   3. Everyone re-clones. A `git pull` into an old clone would merge the old
#      history, blobs and all, straight back in.
#   4. GitHub keeps pull-request refs (refs/pull/*) that still point at the old
#      commits, and a push cannot touch them. Ask GitHub Support to purge
#      cached views and dereference them:
#      https://docs.github.com/en/authentication/keeping-your-account-and-data-secure/removing-sensitive-data-from-a-repository
set -eu

[ $# -eq 2 ] || { sed -n '4,9p' "$0" | sed 's/^# \{0,1\}//' >&2; exit 2; }
SOURCE="$1"
WORK="$2"

git filter-repo --version >/dev/null 2>&1 \
  || { echo "purge: git-filter-repo is required (pip install git-filter-repo)" >&2; exit 1; }
[ ! -e "$WORK" ] || { echo "purge: $WORK exists; give a directory that does not" >&2; exit 1; }

# What to drop. Everything that was ever a SQLite file at any path.
set -- --path-glob '*.db' --path-glob '*.sqlite' --path-glob '*.sqlite3' --path-glob '*.db-journal'

echo "==> Mirror-cloning $SOURCE"
git clone --quiet --mirror "$SOURCE" "$WORK"
cd "$WORK"

before_commits="$(git rev-list --all | wc -l | tr -d ' ')"
before_size="$(git count-objects -vH | sed -n 's/^size-pack: //p')"

# The accounts to rotate: every username in every version of every database
# blob, read before the blobs are gone. Usernames only; nothing secret is
# printed.
echo "==> Reading the users table out of each committed database"
ACCOUNTS="$(mktemp)"
SCRATCH="$(mktemp -d)"
trap 'rm -rf "$SCRATCH" "$ACCOUNTS"' EXIT
git rev-list --objects --all | awk 'NF > 1' | while read -r blob path; do
  case "$path" in *.db|*.sqlite|*.sqlite3) ;; *) continue ;; esac
  [ "$(git cat-file -t "$blob")" = blob ] || continue
  git cat-file blob "$blob" > "$SCRATCH/$blob.db"
  if command -v sqlite3 >/dev/null 2>&1; then
    sqlite3 "$SCRATCH/$blob.db" "SELECT username FROM users;" 2>/dev/null >> "$ACCOUNTS" || true
  fi
done
blobs="$(git rev-list --objects --all | awk 'NF > 1 && ($2 ~ /\.(db|sqlite|sqlite3)$/)' | wc -l | tr -d ' ')"

echo "==> Rewriting history without them"
git filter-repo --force --invert-paths "$@"

echo "==> Verifying"
left="$(git rev-list --objects --all | awk 'NF > 1 && ($2 ~ /\.(db|sqlite|sqlite3|db-journal)$/)' | wc -l | tr -d ' ')"
if [ "$left" != 0 ]; then
  echo "purge: FAILED: $left database blobs are still reachable" >&2
  exit 1
fi
if [ -n "$(git log --all --format=%H -- '*.db' '*.sqlite' '*.sqlite3')" ]; then
  echo "purge: FAILED: git log still finds commits touching a database file" >&2
  exit 1
fi
git fsck --no-progress --connectivity-only >/dev/null

after_commits="$(git rev-list --all | wc -l | tr -d ' ')"
after_size="$(git count-objects -vH | sed -n 's/^size-pack: //p')"

echo
echo "Rewritten mirror in $WORK"
echo "  database blobs removed: $blobs (none remain; git log -- '*.db' is empty)"
echo "  commits: $before_commits before, $after_commits after (commits that only touched a database are gone)"
echo "  pack size: $before_size before, $after_size after"
echo
if [ -s "$ACCOUNTS" ]; then
  echo "Accounts whose password hashes were in history -- rotate each one, wherever it exists:"
  sort -u "$ACCOUNTS" | sed 's/^/  - /'
elif command -v sqlite3 >/dev/null 2>&1; then
  echo "No users table was found in any committed database."
else
  echo "sqlite3 is not installed, so the exposed accounts were not listed. Install it and rerun."
fi
echo
echo "NOTHING HAS BEEN PUSHED. When the owner has agreed, rotated the accounts above and"
echo "warned everyone with a clone:"
echo "  cd $WORK"
echo "  git remote add origin <the GitHub URL>    # filter-repo removes it on purpose"
echo "  git push --force --all origin"
echo "  git push --force --tags origin"
