# Testing Standards Enforcement

Enforce strict testing patterns and AAA convention.

## AAA Naming Convention (REQUIRED)
- Test names must follow exact pattern: `test_method__scenario__expected`
  - `method` = the method being tested (Act)
  - `scenario` = input conditions (Arrange)
  - `expected` = expected outcome (Assert)
- Example: `test_fetch__valid_cid__returns_content`
- Flag any test not following this pattern

## AAA Structure
- Check tests have clear Arrange-Act-Assert sections separated by blank lines
- Verify unit tests use mocks from conftest appropriately (web3 fixture for unit, web3_integration for integration)
- Flag tests that don't clearly separate setup, execution, and verification phases