---
applyTo: "tests/**/*.py"
---

# Testing Standards Enforcement

Enforce strict testing patterns and AAA convention.

## AAA Naming Convention (REQUIRED)
- Test names must follow exact pattern: `test_method__scenario__expected`
  - `method` = the method being tested (Act)
  - `scenario` = input conditions (Arrange)
  - `expected` = expected outcome (Assert)
- Example: `test_fetch__valid_cid__returns_content`
- Prefer this naming for new or substantially edited tests
- Do not flag untouched legacy tests solely for naming unless the PR is already modifying them

## AAA Structure
- Check tests have clear Arrange-Act-Assert sections separated by blank lines
- Verify unit tests use mocks from conftest appropriately (web3 fixture for unit, web3_integration for integration)
- Flag tests that don't clearly separate setup, execution, and verification phases

## Repo-Specific Test Rules
- Every test must be marked with either `@pytest.mark.unit` or `@pytest.mark.integration`
- `mainnet`, `testnet`, and `fork` markers should only appear together with `@pytest.mark.integration`
- Unit tests must not rely on real network access because `tests/conftest.py` blocks sockets
- When protocol logic changes, prefer focused assertions on frame math, bunker/safe-border behavior, report ordering, and contract interaction boundaries instead of only happy-path smoke tests
