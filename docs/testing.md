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
