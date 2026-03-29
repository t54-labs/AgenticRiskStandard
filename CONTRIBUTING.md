# Contributing to ARS

Thank you for your interest in contributing to the Agentic Risk Standard.

## Getting Started

```bash
# Clone and install
git clone <repo-url>
cd ARS
pip install -e ".[dev,client]"

# Run tests
pytest tests/ -v
```

## Development

The project is organized into four packages:

- `src/abstract_ars/` — Abstract protocol (models, state machine, crypto, escrow, settlement)
- `src/abstract_ars_client/` — Abstract protocol client SDK
- `src/ap2/server/` — Concrete AP2 server (mandates, roles, x402, live escrow)
- `src/ap2/client/` — Concrete AP2 client SDK

When adding features, follow the inheritance pattern: define abstractions in `ars/`/`ars_client/`, extend in `ap2/server/`/`ap2/client/`.

## Code Style

This project uses [ruff](https://docs.astral.sh/ruff/) for linting:

```bash
ruff check .
ruff format .
```

## Testing

Every change should include tests. Tests are organized to mirror the package structure:

```
tests/
  test_ars/       — Base ARS protocol tests
  test_ap2/       — AP2 implementation tests
  test_client/    — Client SDK tests
```

Run the full suite with `pytest tests/ -v`.

## Pull Requests

1. Create a feature branch from `main`
2. Write tests for new functionality
3. Ensure all tests pass
4. Submit a PR with a clear description

## License

By contributing, you agree that your contributions will be licensed under the Apache 2.0 License.
