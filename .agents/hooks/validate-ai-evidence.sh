#!/usr/bin/env bash

set -euo pipefail

hook_input="$(cat || true)"
if printf '%s' "$hook_input" | grep -Eq '"stop_hook_active"[[:space:]]*:[[:space:]]*true'; then
  exit 0
fi

project_dir="${CLAUDE_PROJECT_DIR:-$(git rev-parse --show-toplevel)}"
cd "$project_dir"

evidence_changes="$(
  git status --porcelain --untracked-files=normal -- \
    AI_USAGE.md README.md .claude/settings.json \
    .agents/hooks/validate-ai-evidence.sh docs/ai-evidence docs/ai-evidence.zip
)"

if [[ -z "$evidence_changes" ]]; then
  exit 0
fi

fail() {
  printf 'AI evidence guard: FAIL - %s\n' "$1" >&2
  exit 2
}

git diff --check -- AI_USAGE.md README.md .claude/settings.json \
  .agents/hooks/validate-ai-evidence.sh docs/ai-evidence docs/ai-evidence.zip \
  || fail "whitespace errors remain in submission evidence"

head_sha="$(git rev-parse HEAD)"
grep -Fq "$head_sha" AI_USAGE.md \
  || fail "AI_USAGE.md does not name current HEAD $head_sha"

summary_path="$(
  sed -nE \
    's#.*\]\((docs/ai-evidence/project-tests/[^)]*/SUMMARY\.md)\).*#\1#p' \
    AI_USAGE.md | head -n 1
)"

[[ -n "$summary_path" ]] \
  || fail "AI_USAGE.md has no latest project-test SUMMARY link"
[[ -f "$summary_path" ]] \
  || fail "latest project-test summary does not exist: $summary_path"
grep -Fq "$head_sha" "$summary_path" \
  || fail "latest project-test summary does not name current HEAD $head_sha"

[[ -f docs/ai-evidence.zip ]] \
  || fail "docs/ai-evidence.zip does not exist"
unzip -tq docs/ai-evidence.zip >/dev/null \
  || fail "docs/ai-evidence.zip is not a valid ZIP archive"

for packaged_file in \
  AI_USAGE.md \
  README.md \
  .claude/settings.json \
  .agents/hooks/validate-ai-evidence.sh \
  "$summary_path"
do
  unzip -p docs/ai-evidence.zip "$packaged_file" | cmp -s - "$packaged_file" \
    || fail "ZIP copy is missing or stale: $packaged_file"
done

printf 'AI evidence guard: PASS (%s)\n' "$head_sha"
