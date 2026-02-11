# Testing

Tests in this directory are run using the [pytest](https://docs.pytest.org/en/latest/) framework.
You can run it by running `pytest tests` in the root directory of the repository.

Most tests are unit tests and marked with the `@pytest.mark.unit` decorator.
They use predefined rpc responses and do not require either consensus or beacon nodes.
Rpc and Http responses are stored in the `tests/responses` directory and can be overridden using `--update-responses`
flag while running tests (make sure that you set rpc node environment variables in this case).
They are useful when you do not need to change response data for testing.
In case if you need to test something with using specific responses, you can mock it directly using `add_mock` function from `MockProvider`.

To run tests with a coverage report, run `pytest --cov=src tests` in the root directory of the repository.

## Env variables

| Name                           | Description                                                                 | Required | Example value           |
|--------------------------------|-----------------------------------------------------------------------------|----------|-------------------------|
| `TESTNET_CONSENSUS_CLIENT_URI` | URI of the consensus client node for tests marked with @pytest.mark.testnet | False    | `http://localhost:8545` |
| `TESTNET_EXECUTION_CLIENT_URI` | URI of the execution client node for tests marked with @pytest.mark.testnet | False    | `http://localhost:8545` |
| `TESTNET_KAPI_URI`             | URI of the keys api node for tests marked with @pytest.mark.testnet         | False    | `http://localhost:8545` |

## Mutation Testing

Mutation testing is used to evaluate the quality of the test suite by introducing small changes (mutations) to the source code and verifying that tests catch these changes.

### Running Mutation Tests

Run mutation tests on specific files or directories:

```bash
# Run on a specific mutation target and specific test files
poetry run mutmut run \
    --paths-to-mutate=src/services/staking_vaults.py \
    --runner="pytest -x -m unit -q tests/modules/accounting/staking_vault"
```

### Viewing Results

```bash
# View summary of results
poetry run mutmut results

# View details of a specific mutant
poetry run mutmut show <id>

# Generate HTML report (opens in browser)
poetry run mutmut html
```

### Understanding Results

- **🎉 Killed**: Test suite caught the mutation (good!)
- **🙁 Survived**: Mutation wasn't caught (test gap identified)
- **⏰ Timeout**: Tests took too long (possible infinite loop)
- **🤔 Suspicious**: Tests took longer than expected

**Mutation Score** = (Killed Mutants / Total Mutants) × 100%

A mutation score above 75% indicates good test coverage. Surviving mutants often reveal:
- Missing boundary condition tests
- Inadequate assertion checks
- Untested edge cases

### Configuration

Mutation testing is configured in `pyproject.toml` under `[tool.mutmut]`:
- Tests are run with `-m unit` flag (unit tests only for speed)
- Tests stop on first failure (`-x` flag) for faster feedback
- Results cached in `.mutmut-cache` file
