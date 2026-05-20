# MultiMemD (MMD)

Per-user Markdown memory plugin for Hermes agent. Zero infrastructure dependency.

## What It Does

Adds per-user memory isolation to Hermes. Each user gets their own `{user_id}.md` (≤ 200 lines). MMD loads it before each reply and updates it at session end using one LLM call.

## Install

```bash
# Link or copy the plugin into Hermes' memory plugin directory
ln -s "$(pwd)/plugin" ~/.hermes/plugins/memory/mmd

# Set the data directory (defaults to ~/.hermes/mmd if not set)
export MMD_DATA_DIR=~/.hermes/mmd

# Enable the plugin
hermes memory setup mmd
```

## Usage (bot side)

```python
# Before each conversation, bind the user
memory_provider.initialize(session_id, user_id=f"telegram_{message.from_user.id}")
```

## Run Tests

```bash
python3 -m pytest tests/ -v
```

## Docs

- [Project Plan](docs/plan.md)
- [MMD Spec](docs/adr/0009-mmd-spec.md)
- [Roadmap](docs/roadmap.md)
