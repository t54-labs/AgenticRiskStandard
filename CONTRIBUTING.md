# Contributing to ARS

Thank you for your interest in contributing to the Agentic Risk Standard.

## Getting Started

```bash
# Clone and install
git clone https://github.com/t54-labs/AgenticRiskStandard.git
cd AgenticRiskStandard
pip install -e ".[dev,client,ap2,vi]"

# Run tests
pytest tests/ -v
```

The optional extras are independent: `ap2` pulls in the x402 SDK and web3, `vi` pulls in
`cryptography` for ES256/SD-JWT, and `client` pulls in httpx and click for the SDKs and CLIs.
Install only the extras for the layer you are working on if you prefer a lighter environment.

## Development

The project is organized into one abstract layer and two concrete implementations:

- `src/abstract_ars/` — Abstract protocol (models, state machine, crypto, vaults, settlement)
- `src/abstract_ars_client/` — Abstract protocol client SDK
- `src/ap2/server/` — Concrete AP2 server (mandates, roles, x402, live escrow)
- `src/ap2/client/` — Concrete AP2 client SDK
- `src/vi/server/` — Concrete VI server (SD-JWT credential chain, roles, selective disclosure)
- `src/vi/client/` — Concrete VI client SDK

When adding features, follow the inheritance pattern: define abstractions in `abstract_ars/` and
`abstract_ars_client/`, then extend them in `ap2/` and `vi/`. A change that both concrete
implementations would need belongs in the abstract layer, not duplicated in each.

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
  test_abstract_ars/  — Base ARS protocol tests
  test_ap2/           — AP2 implementation tests
  test_vi/            — VI implementation tests
  test_client/        — Abstract and AP2 client SDK tests
  test_vi_client/     — VI client SDK tests
```

Run the full suite with `pytest tests/ -v`, or a single layer with `pytest tests/test_vi/ -v`.

Runnable end-to-end scenarios live in `samples/scenarios/` (one directory per modality, each with
a `run.sh`). They are a good way to sanity-check a protocol change against a full flow.

## Pull Requests

1. Create a feature branch from `main`
2. Write tests for new functionality
3. Ensure all tests pass
4. Submit a PR with a clear description

## License

By contributing, you agree that your contributions will be licensed under the Apache 2.0 License.
