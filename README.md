# KubeMedic

[![CI](https://github.com/ashpb2018/k8s-ai-troubleshooter/actions/workflows/ci.yml/badge.svg)](https://github.com/ashpb2018/k8s-ai-troubleshooter/actions/workflows/ci.yml)
![Python](https://img.shields.io/badge/python-3.10%2B-blue)
![License](https://img.shields.io/badge/license-MIT-green)

**An LLM-driven agent that diagnoses and repairs Kubernetes clusters — then writes the runbook for you.**

KubeMedic gives a large language model a curated, safe set of Kubernetes operations and lets it work like an on-call SRE: it triages the cluster, correlates logs, events and resource pressure to find a root cause, applies the least-invasive fix (with your confirmation), and records a Markdown runbook for every incident it handles.

It runs against any of three backends — a local **Ollama** model, **AWS Bedrock**, or **OpenAI** — behind one interface, so you can develop offline and deploy with a hosted model without changing a line of agent code.

---

## Highlights

- **Provider-agnostic agent** — one `ChatBackend` interface, three implementations (Ollama / Bedrock / OpenAI). Swap models via config, not code.
- **Tool-calling loop** — the model reasons, calls a Kubernetes tool, reads the result, and repeats until it can explain the problem.
- **Safe by default** — every mutating action (restart, scale, rollback, delete, apply, patch) is gated behind an explicit confirmation unless you opt into `--auto-approve`.
- **Automatic runbooks** — each investigation is distilled into a structured Markdown runbook (root cause, fix, verification, prevention) plus a browsable index.
- **Two front ends** — a Rich-powered CLI and a FastAPI + React web UI that streams the agent's reasoning over WebSockets.

---

## Architecture

```
src/kubemedic/
├── settings.py         # layered configuration (env / .env)
├── assembly.py         # wires the runtime components together
├── providers/          # LLM backends behind one interface
│   ├── base.py         #   ChatBackend contract
│   ├── messages.py     #   backend-neutral Conversation / Turn / Completion
│   ├── ollama_backend.py
│   ├── openai_backend.py
│   ├── bedrock_backend.py
│   └── registry.py     #   settings -> concrete backend
├── cluster/            # Kubernetes access
│   ├── client.py       #   typed API-client wrapper
│   ├── operations.py   #   the tools the agent can call
│   └── formatting.py   #   compact text rendering
├── agent/              # the reasoning core
│   ├── toolspec.py     #   JSON tool schemas + handler mapping
│   ├── loop.py         #   the reason-act loop (Investigator)
│   ├── incident.py     #   structured incident record
│   └── events.py       #   transport-neutral event stream
├── runbooks/           # Markdown runbook writer + index
├── cli.py              # Typer CLI
└── web/                # FastAPI app (WebSocket streaming + REST)
```

The agent never talks to an SDK directly. It emits a stream of typed **events** that either the CLI renderer or the web layer consumes, and it calls **operations** through a schema-to-method registry, so the model-facing tool names and the Python implementation can evolve independently.

---

## Quick start

```bash
# 1. Install (pick the extras you need)
python3 -m venv .venv && source .venv/bin/activate
pip install -e '.[ollama]'      # or '.[openai]', '.[bedrock]', or '.[all]'

# 2. Configure
cp .env.example .env            # then edit LLM_PROVIDER and credentials

# 3. Run
kubemedic chat                  # interactive session
kubemedic scan                  # one-shot cluster sweep + runbook
kubemedic fix "nginx pods in CrashLoopBackOff"
kubemedic runbooks              # list generated runbooks
```

KubeMedic uses your current `kubectl` context by default. Point it elsewhere with `--context` or `K8S_CONTEXT`.

---

## Backends

Set `LLM_PROVIDER` in `.env` to `ollama`, `bedrock`, or `openai`.

**Ollama** (local, no API key)
```env
LLM_PROVIDER=ollama
OLLAMA_HOST=http://localhost:11434
OLLAMA_MODEL=llama3.2
```

**AWS Bedrock** (bearer token, IAM keys, or the default credential chain)
```env
LLM_PROVIDER=bedrock
AWS_REGION=us-east-1
BEDROCK_MODEL_ID=us.anthropic.claude-sonnet-4-5-20250929-v1:0
BEDROCK_API_KEY=<bearer-token>       # or AWS_ACCESS_KEY_ID / AWS_SECRET_ACCESS_KEY
```

**OpenAI**
```env
LLM_PROVIDER=openai
OPENAI_API_KEY=<key>
OPENAI_MODEL=gpt-4o
```

---

## Web UI

```bash
pip install -e '.[all]'
bash web/start.sh          # dev:  backend + Vite hot reload -> http://localhost:5173
bash web/start.sh prod     # prod: build UI and serve from FastAPI -> http://localhost:8000
```

The UI streams the agent's tool calls and reasoning live, prompts for confirmation before destructive actions, and browses saved runbooks. Backend settings can be edited from the Settings page and are persisted to `.env`.

---

## Development

```bash
pip install -e '.[dev]'
pytest                 # run the test suite
ruff check src tests   # lint
```

The tests cover the pure-logic core — the agent loop (with a scripted fake backend), provider message serialisation, incident parsing, runbook rendering, settings, and formatting — without needing a live cluster or any LLM credentials.

---

## Safety model

- Read operations run freely.
- Mutating operations (`restart`, `scale`, `rollback`, `delete`, `apply`, `patch`, and any mutating `kubectl` verb) require confirmation.
- `--auto-approve` / `AUTO_FIX=true` removes the prompts — intended for non-production automation only.

---

## License

MIT — see [LICENSE](LICENSE) and [NOTICE](NOTICE).
