# Same checks as CI. Run `just check` before pushing.

default: check

# Pre-commit hooks (hygiene, ruff, zizmor, gitleaks) + unit tests
check: hooks test evals-check

# Every pre-commit hook over every file
hooks:
    uvx pre-commit@4.6.2 run --all-files --show-diff-on-failure

test:
    uv run --locked python -m unittest discover -s tests -t .

# Install the hooks so they run on every local commit
install-hooks:
    uvx pre-commit@4.6.2 install

# Auto-fix what ruff can, then format
fix:
    uvx ruff@0.17.0 check --fix .
    uvx ruff@0.17.0 format .

# Eval harness: format, vet, unit tests, and a smoke run against the mock contestant
evals-check:
    test -z "$(gofmt -l evals)" || (gofmt -l evals && exit 1)
    go -C evals vet ./...
    go -C evals test ./...
    go -C evals run . -contestants mock -samples 1 > /dev/null

# Boss fight with real models. Runs locally only; one at a time on a laptop.
# just eval reply-draft rock,bass 3
eval stage="reply-draft" contestants="rock" samples="3" *args="":
    go -C evals run . -stage {{stage}} -contestants {{contestants}} -samples {{samples}} {{args}}
