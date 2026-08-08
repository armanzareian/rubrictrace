# Contributing

RubricTrace welcomes focused contributions that improve the reliability, clarity, or integration
surface of LLM-as-judge log audits.

## Development Setup

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e .
make test
make quality
```

## Contribution Guidelines

- Keep detector output deterministic.
- Add fixtures and tests for new detector behavior.
- Avoid printing full judge rationales or private evaluation text in errors.
- Document input schema changes in the README and architecture notes.
- Keep runtime dependencies small and well justified.

## Pull Requests

Before opening a pull request, run:

```bash
make test
make quality
make demo
make eval
```

Include the problem being solved, the user-facing behavior change, and validation performed.
