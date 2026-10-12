#!/usr/bin/env bash
# Apply light-labs repository settings. Idempotent: safe to re-run.
# Run after main exists on GitHub (the ruleset blocks direct pushes). Requires a public repo (rulesets and free secret scanning) and gh with admin rights.
set -euo pipefail
REPO="${1:-kellypj24/light-labs}"

# Squash-only merges with the PR title, delete branches after merge.
gh api -X PATCH "repos/$REPO" --silent \
  -F allow_squash_merge=true -F allow_merge_commit=false -F allow_rebase_merge=false \
  -f squash_merge_commit_title=PR_TITLE -f squash_merge_commit_message=PR_BODY \
  -F delete_branch_on_merge=true -F allow_auto_merge=true

# Secret scanning + push protection, Dependabot alerts and security updates.
gh api -X PATCH "repos/$REPO" --silent --input - <<'JSON'
{"security_and_analysis": {
  "secret_scanning": {"status": "enabled"},
  "secret_scanning_push_protection": {"status": "enabled"}}}
JSON
gh api -X PUT "repos/$REPO/vulnerability-alerts" --silent
gh api -X PUT "repos/$REPO/automated-security-fixes" --silent

# CodeQL default setup (Python + Actions).
gh api -X PATCH "repos/$REPO/code-scanning/default-setup" --silent \
  -f state=configured -f query_suite=default

# main: changes arrive by PR, CI Success must pass, no force-push or deletion.
# No bypass actors, so not even an admin merge can land a red CI.
name="main: PR + CI Success (no bypass)"
existing=$(gh api "repos/$REPO/rulesets" -q ".[] | select(.name == \"$name\") | .id")
body=$(cat <<JSON
{"name": "$name", "target": "branch", "enforcement": "active",
 "conditions": {"ref_name": {"include": ["~DEFAULT_BRANCH"], "exclude": []}},
 "bypass_actors": [],
 "rules": [
   {"type": "deletion"},
   {"type": "non_fast_forward"},
   {"type": "pull_request", "parameters": {
     "required_approving_review_count": 0, "dismiss_stale_reviews_on_push": false,
     "require_code_owner_review": false, "require_last_push_approval": false,
     "required_review_thread_resolution": false, "allowed_merge_methods": ["squash"]}},
   {"type": "required_status_checks", "parameters": {
     "strict_required_status_checks_policy": false,
     "required_status_checks": [{"context": "CI Success"}]}}]}
JSON
)
if [ -n "$existing" ]; then
  echo "$body" | gh api -X PUT "repos/$REPO/rulesets/$existing" --silent --input -
else
  echo "$body" | gh api -X POST "repos/$REPO/rulesets" --silent --input -
fi

echo "settings applied to $REPO"
