# Same checks as CI. Run `just check` before pushing.

default: check

# Pre-commit hooks (hygiene, ruff, zizmor, gitleaks) + unit tests
check: hooks test

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
