# Testing

Tests in this directory are run using the [pytest](https://docs.pytest.org/en/latest/) framework.
You can run it by running `pytest tests` in the root directory of the repository.

Most tests are unit tests and marked with the `@pytest.mark.unit` decorator.
They use predefined rpc responses and do not require either consensus or beacon nodes.
Rpc responses are stored in the `tests/responses` directory 
and can be updated using `--save-responses` flag while running tests (make sure that you set rpc node environment variables in this case).
It useful when you do not need to change response data for testing.
In case if you need to test something with using specific responses, you can mock it directly, see `tests/mocks.py`.
