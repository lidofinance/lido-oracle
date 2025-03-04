#!/bin/bash

COMMIT_MSG_FILE=$1
COMMIT_MSG=$(head -n 1 "$COMMIT_MSG_FILE")

REGEX="^(feat|fix|docs|chore|refactor|test)(\(.+\))?: .+"

if ! grep -qE "$REGEX" <<< "$COMMIT_MSG"; then
    echo "❌ ERROR: Commit message does not follow Conventional Commits format!"
    exit 1
fi

echo "✅ Commit message format is valid!"
