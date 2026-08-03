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

summary_path="$(
  sed -nE \
    's#.*\]\((docs/ai-evidence/project-tests/[^)]*/SUMMARY\.md)\).*#\1#p' \
    AI_USAGE.md | head -n 1
)"

[[ -n "$summary_path" ]] \
  || fail "AI_USAGE.md has no latest project-test SUMMARY link"
[[ -f "$summary_path" ]] \
  || fail "latest project-test summary does not exist: $summary_path"

source_state_path="$(dirname "$summary_path")/source-state.txt"
[[ -f "$source_state_path" ]] \
  || fail "latest project-test source state does not exist: $source_state_path"
runtime_commit="$(sed -nE 's/^verified_runtime_commit=([0-9a-f]{40})$/\1/p' "$source_state_path")"
[[ -n "$runtime_commit" ]] \
  || fail "latest source state has no verified_runtime_commit"
git cat-file -e "$runtime_commit^{commit}" 2>/dev/null \
  || fail "verified runtime commit does not exist: $runtime_commit"
git merge-base --is-ancestor "$runtime_commit" HEAD \
  || fail "verified runtime commit is not an ancestor of HEAD: $runtime_commit"
grep -Fq "$runtime_commit" AI_USAGE.md \
  || fail "AI_USAGE.md does not name verified runtime commit $runtime_commit"
grep -Fq "$runtime_commit" "$summary_path" \
  || fail "latest summary does not name verified runtime commit $runtime_commit"

runtime_paths=(
  apps
  packages
  fixtures
  supabase
  docs/api-data-contract.md
  docs/api-명세서.md
)
[[ -z "$(git status --porcelain --untracked-files=normal -- "${runtime_paths[@]}")" ]] \
  || fail "runtime paths have uncommitted changes after verified commit"
git diff --quiet "$runtime_commit"..HEAD -- "${runtime_paths[@]}" \
  || fail "runtime paths changed after verified commit $runtime_commit"

[[ -f docs/ai-evidence.zip ]] \
  || fail "docs/ai-evidence.zip does not exist"
unzip -tq docs/ai-evidence.zip >/dev/null \
  || fail "docs/ai-evidence.zip is not a valid ZIP archive"

for packaged_file in \
  AI_USAGE.md \
  README.md \
  .claude/settings.json \
  .agents/hooks/validate-ai-evidence.sh \
  "$summary_path" \
  "$source_state_path"
do
  unzip -p docs/ai-evidence.zip "$packaged_file" | cmp -s - "$packaged_file" \
    || fail "ZIP copy is missing or stale: $packaged_file"
done

printf 'AI evidence guard: PASS (runtime=%s head=%s)\n' \
  "$runtime_commit" "$(git rev-parse HEAD)"
