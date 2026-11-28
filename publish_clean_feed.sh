#!/usr/bin/env bash
set -euo pipefail

git config user.name 'github-actions[bot]'
git config user.email '41898282+github-actions[bot]@users.noreply.github.com'

# On a concurrent producer push, discard only the unpublished generated
# projection in this disposable Actions checkout and regenerate from latest
# main. Rebasing a stale projection would break source/JD shard consistency.
for attempt in 1 2 3 4 5; do
    git fetch origin main
    git checkout --detach origin/main
    git reset --hard origin/main
    python public_quality.py
    git add -A feed/clean
    if git diff --cached --quiet; then
        echo 'No new clean projection.'
        exit 0
    fi
    git commit -m 'data: refresh clean public feed [skip ci]'
    if git push origin HEAD:main; then
        exit 0
    fi
    echo "::warning::Concurrent main update; rebuild projection (attempt $attempt)"
done
echo '::error::Clean publication could not obtain a consistent main snapshot'
exit 1
