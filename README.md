# Paula Port — Hub

Hexagonal core of Paula Port. It receives orders from the PC agent (and Alexa), resolves the intent with the Claude API and publishes actions, replies and alerts through RabbitMQ.

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
│   └── outbound/    # claude, rabbitmq (actions to pc-agent), alexa (alerts)
└── config/
alexa-skill/         # Alexa Custom Skill + AWS Lambda for notifications
tests/               # unit/, integration/
scripts/
```

Dependency rule: `adapters → application / ports → domain`. `domain/` never imports from `adapters/`.

## Setup

Requires Python 3.11+, RabbitMQ and Tailscale.

```bash
python -m venv .venv
.venv\Scripts\activate          # Windows
pip install -e ".[dev]"
cp .env.example .env            # then fill in the keys
pytest
```

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md): English only, `main` ← `develop` ← `feat/*` branches, Conventional Commits.
