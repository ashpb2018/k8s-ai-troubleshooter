# Contributing to KubeMedic

Thanks for your interest in improving KubeMedic.

## Development setup

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -e '.[all,dev]'
```

## Before opening a pull request

- Run the linter: `ruff check src tests`
- Run the tests: `pytest`
- Keep changes focused and add tests for new behaviour.

## Project layout

The core lives under `src/kubemedic/`:

- `providers/` — LLM backends behind one interface
- `cluster/` — Kubernetes client and the operations the agent can call
- `agent/` — the reason-act loop, tool catalogue, and incident model
- `runbooks/` — Markdown runbook writer
- `web/` — FastAPI app for the browser UI

## Reporting issues

Open a GitHub issue with clear reproduction steps, the backend/model in use,
and any relevant runbook or log output (redact secrets first).
