set dotenv-load
set shell := ['bash', '-c']

@_:
    just --list

# Run offline tests against the fake Packet Tracer
[group('qa')]
test args='':
    uv run -m pytest {{args}}

# Run tests against the running Packet Tracer (uses PT_* env vars)
[group('qa')]
test-live args='':
    USE_MOCKS=false uv run -m pytest {{args}}

# Run all code style and lint checks
[group('qa')]
check:
    uv run black --check src/ tests/
    uv run isort --check-only src/ tests/
    uv run flake8 src/ tests/

# Build this machine's ExApp file (.pta, random key) with the installed Packet Tracer's meta tool
[group('build')]
setup:
    uv run pt-mcp setup

# Check Packet Tracer, IPC, ExApp registration and API spec
[group('qa')]
doctor:
    uv run pt-mcp doctor

# Re-record the verified IPC method allow-list against the running Packet Tracer (use a scratch network)
[group('build')]
verify-methods:
    rm -f /tmp/pt-verified.txt
    PT_RECORD_CALLS=/tmp/pt-verified.txt USE_MOCKS=false uv run -m pytest -q
    uv run python -c "import json,sys; m=sorted(set(open('/tmp/pt-verified.txt').read().split())); d=json.load(open('src/pt_mcp/data/verified_methods.json')); d['methods']=m; json.dump(d,open('src/pt_mcp/data/verified_methods.json','w'),indent=1); print(len(m),'methods')"

[group('build')]
build:
    uv build

[group('lifecycle')]
install:
    uv sync --no-dev

[group('lifecycle')]
dev-install:
    uv sync

[group('lifecycle')]
update:
    uv sync --upgrade

[group('lifecycle')]
[confirm("This will delete .venv, caches, and __pycache__ directories. Continue?")]
clean:
    rm -rf .venv .pytest_cache .coverage htmlcov
    find . -type d -name "__pycache__" -exec rm -r {} +
