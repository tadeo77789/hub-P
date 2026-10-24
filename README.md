# Paula Port — Hub

Hexagonal core of Paula Port. It receives orders from the PC agent (and Alexa), resolves the intent with a local model (Qwen in Ollama) and publishes actions, replies and alerts through RabbitMQ.

## Layout

```
src/paula_hub/
├── domain/          # intents, orders, results; no external dependencies
├── application/     # use cases that orchestrate the domain
├── ports/
│   ├── inbound/     # interfaces the adapters call into
│   └── outbound/    # interfaces the core calls out through
├── adapters/
│   ├── inbound/     # rabbitmq (orders from pc-agent), alexa
│   └── outbound/    # ollama, rabbitmq (actions to pc-agent), alexa (alerts)
└── config/
alexa-skill/         # Alexa Custom Skill + AWS Lambda for notifications
tests/               # unit/, integration/
scripts/
```

Dependency rule: `adapters → application / ports → domain`. `domain/` never imports from `adapters/`.

## Setup

Requires Python 3.11+, RabbitMQ and [Ollama](https://ollama.com) with the model pulled.

```bash
ollama pull qwen3:4b-instruct   # about 2.5 GB, runs on the GPU
python -m venv .venv
.venv\Scripts\activate          # Windows
pip install -e ".[dev]"
cp .env.example .env            # then fill in the keys
docker compose -f deploy/docker-compose.yml up -d   # RabbitMQ on localhost
pytest                          # integration tests run when RabbitMQ is reachable
python -m paula_hub             # start the hub
```

If port 5672 is taken, set `RABBITMQ_PORT` (and `RABBITMQ_UI_PORT`) before `docker compose up` and update `RABBITMQ_URL` to match.

Start at logon: `powershell -ExecutionPolicy Bypass -File scripts\install-startup.ps1`.

## How it works

- Orders arrive on `hub.orders`; the core sends the text to Qwen (`qwen3:4b-instruct` in Ollama, thinking off for speed) with the command whitelist as tools. Everything runs on the PC; nothing goes to a cloud model.
- Tool calls become signed `Action` messages on `agent.actions`. Destructive ones (`shutdown_pc`) first return a `question` result with Yes / No options and only run after a `confirm` order.
- The agent reports each action on `hub.events`; the core feeds the outcome back to the model and replies on `agent.results`.
- Actions that take longer than `LONG_TASK_SECONDS`, and replies to Alexa orders, also go to Alexa (`alexa-skill/`).
- If Ollama is down or slow (`OLLAMA_TIMEOUT`), the agent gets an error result and the robot turns angry.

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md): English only, `main` ← `develop` ← `feat/*` branches, Conventional Commits.
