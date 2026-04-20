# Testing

## Running tests

#### Docker (recommended)

```bash
make test
```

Run specific tests:
```bash
make test ORACLE_TEST_PATH=tests/modules/accounting/
```

#### Local

```bash
poetry run pytest tests/
```


## Testing strategy

Target ratio: **~90% unit tests, ~10% integration tests**.

Integration tests depend on external Ethereum nodes which can be unstable or slow. Unit tests are fast, reliable, and don't require network access, making them the preferred choice for most test cases.

Target coverage:
- **95–100%** for core modules (any business logic, reports cycle, data validation)
- **85–95%** for auxiliary parts (infrastructure layer, metrics, logging, utilities, etc.)

If 100% is not achievable (dead code, generated code, etc.), 98%+ is acceptable with justification for uncovered lines.

Every test **must** have either `@pytest.mark.unit` or `@pytest.mark.integration` marker. Tests without markers will fail.

Unit and integration markers are mutually exclusive - a test cannot have both.

### Unit tests

#### `@pytest.mark.unit`

The primary type of tests. Use mocks to isolate the code under test from external dependencies. Network access is automatically blocked - any attempt to make a real network call will fail the test.

When to use:
- Testing business logic
- Testing data transformations
- Testing error handling
- Testing edge cases

### Integration tests

#### `@pytest.mark.integration`

Required for verifying interactions with real external systems.

#### `@pytest.mark.mainnet`

Tests against real Ethereum mainnet. Use for:
- Verifying contract ABIs match deployed contracts
- Tests that check oracle cycle runs without errors
- Testing real contract interactions

#### `@pytest.mark.testnet`

Tests against testnet. Use for:
- Testing new contracts/features not yet deployed to mainnet
- Testing against different contract configurations

Once the feature is deployed to mainnet, these tests should be migrated to `@pytest.mark.mainnet`.

#### `@pytest.mark.fork`

End-to-end tests using [Anvil](https://getfoundry.sh/anvil/overview) to fork mainnet state. Use for:
- Testing complete oracle reporting cycle
- Verifying the oracle can successfully submit reports
- Testing complex multi-step workflows
- Any test that requires sending Ethereum transactions

Located in `tests/fork/`.

## Web3 fixtures

The global `conftest.py` provides two web3 fixtures:

### `web3` (for unit tests)

Mocked Web3 instance using `eth_tester` library with `MockBackend`. This creates an in-memory Ethereum emulator without real EVM execution. All contracts are replaced with mock objects, so no actual contract logic runs — this makes tests fast and isolated. Configure specific return values in tests as needed:

```python
@pytest.mark.unit
class TestMyModule:

    def test_something(self, web3):
        web3.lido_contracts.staking_router.functions.getStakingModuleIds.return_value.call.return_value = [1, 2]
        # ... test logic
```

### `web3_integration` (for integration tests)

Real Web3 instance connected to actual nodes. Requires environment variables (`EXECUTION_CLIENT_URI`, `CONSENSUS_CLIENT_URI`, `KEYS_API_URI`).

## Writing tests

### Naming convention

Test names follow the pattern:

```
test_<method_name>__<scenario>__<expected_behavior>
```

Parts are separated by double underscores (`__`):

- `<method_name>` - name of the method being tested
- `<scenario>` - input conditions or state
- `<expected_behavior>` - what should happen

Examples:
- `test_fetch__valid_cid__returns_content`
- `test_fetch__request_fails__raises_fetch_error`
- `test_publish__store_status_done__skips_upload_request`

### AAA pattern

Structure tests using the Arrange-Act-Assert pattern:

```python
def test_calculate__two_positive_numbers__returns_sum(self, calculator):
    # Arrange
    a = 5
    b = 3
    expected = 8

    # Act
    result = calculator.calculate(a, b)

    # Assert
    assert result == expected
```

Keep each section visually separated with blank lines. Comments (`# Arrange`, `# Act`, `# Assert`) are optional.

### Test class organization

Group related tests in classes marked with the appropriate marker:

```python
@pytest.mark.unit
class TestCalculator:

    @pytest.fixture
    def calculator(self):
        return Calculator(precision=2)

    def test_add__positive_numbers__returns_sum(self, calculator):
        result = calculator.add(2, 3)
        assert result == 5

    def test_add__negative_numbers__returns_sum(self, calculator):
        result = calculator.add(-2, -3)
        assert result == -5
```

### Mocking HTTP requests

Use the `responses` library for mocking HTTP requests:

```python
import responses

@pytest.mark.unit
class TestApiClient:

    @responses.activate
    def test_get__success__returns_data(self, client):
        responses.add(
            responses.GET,
            "https://api.example.com/data",
            json={"key": "value"},
            status=200,
        )

        result = client.get("/data")

        assert result == {"key": "value"}
        assert len(responses.calls) == 1
```

## Environment variables

For integration tests:

| Name                           | Description                                              | Required |
|--------------------------------|----------------------------------------------------------|----------|
| `CONSENSUS_CLIENT_URI`         | Consensus client URI (for mainnet tests)                 | Yes*     |
| `EXECUTION_CLIENT_URI`         | Execution client URI (for mainnet tests)                 | Yes*     |
| `KEYS_API_URI`                 | Keys API URI (for mainnet tests)                         | Yes*     |
| `TESTNET_CONSENSUS_CLIENT_URI` | Consensus client URI (for testnet tests)                 | Yes*     |
| `TESTNET_EXECUTION_CLIENT_URI` | Execution client URI (for testnet tests)                 | Yes*     |
| `TESTNET_KAPI_URI`             | Keys API URI (for testnet tests)                         | Yes*     |

*Required only when running corresponding integration tests.

## Mutation Testing

Mutation testing evaluates test suite quality by introducing small source code changes (mutations) and verifying that tests detect them. The project uses [mutmut 3.x](https://mutmut.readthedocs.io/).

### Running Mutation Tests

**Always run via Docker** — mutmut uses `os.fork()` internally, which is unsafe on macOS with Python 3.14 and causes segfaults. Docker (Linux) is required.

```bash
# Run full mutation suite — prints emoji summary at the end
make test-mutations

# Show the full list of survived/no-tests/timeout mutants
make mutation-results
```

To target a specific module, edit `paths_to_mutate` in `pyproject.toml` before running:

```toml
[tool.mutmut]
paths_to_mutate = ["src/services/safe_border.py"]
```

Then run `make test-mutations` as usual. Restore the original value when done.

> Results are cached in `.mutmut-cache`. Re-running only tests mutants that haven't been evaluated yet.
> To start fresh: `rm .mutmut-cache mutants/ -rf` before `make test-mutations`.

### Viewing Results

Run these commands from inside the Docker container (`make sh`) or locally if the cache was produced locally:

```bash
# Summary of all results
poetry run mutmut results

# Diff for a specific mutant (use the ID from results)
poetry run mutmut show <id>

# Generate HTML report
poetry run mutmut html
```

### Understanding Results

| Symbol | Name | Meaning |
|--------|------|---------|
| 🎉 | Killed | Tests detected the mutation — good |
| 🙁 | Survived | Mutation was not detected — test gap |
| 🫥 | No tests | No unit tests cover this code path |
| ⏰ | Timeout | Tests exceeded time limit |
| 🤔 | Suspicious | Tests passed but took longer than expected |

**Mutation Score** = Killed / (Killed + Survived) × 100%

A score above 75% indicates solid test coverage. Survived mutants reveal:
- Missing boundary condition tests
- Insufficient assertions (asserting shape but not values)
- Untested branches or edge cases

### Configuration

`pyproject.toml` under `[tool.mutmut]`:

```toml
[tool.mutmut]
paths_to_mutate = ["src/"]          # source files to mutate
tests_dir = ["tests/"]              # test files to run
pytest_add_cli_args = ["-x", "-m", "unit", "-q"]  # unit tests only, stop on first failure
also_copy = ["src/", "assets/"]     # directories copied into the mutants/ sandbox
do_not_mutate = ["src/providers/execution/contracts/*"]  # excluded paths
```

### Test Isolation Requirement

mutmut 3.x runs the stats phase and clean tests in the **same Python process**. Class-level attribute assignments without cleanup persist across the entire test session and will break the clean test phase.

**Wrong** — direct class mutation persists after the test:

```python
def test_something():
    MyClass._method = Mock()   # leaks into all subsequent tests!
    obj = MyClass(...)
```

**Correct** — use `monkeypatch`, which automatically restores state after each test:

```python
def test_something(monkeypatch):
    monkeypatch.setattr(MyClass, '_method', Mock())
    obj = MyClass(...)
```

Instance-level patching (`obj._method = Mock()`) is safe because it doesn't affect the class.
