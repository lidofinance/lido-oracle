# Testing

Tests in this directory are run using the [pytest](https://docs.pytest.org/en/latest/) framework.
You can run it by running `pytest tests` in the root directory of the repository.

Most tests are unit tests and marked with the `@pytest.mark.unit` decorator.
They use predefined rpc responses and do not require either consensus or beacon nodes.
Rpc and Http responses are stored in the `tests/responses` directory 
and can be overriden using `--save-responses` flag while running tests (make sure that you set rpc node environment variables in this case).
Another argument `--update-responses` can be used to add new responses and remove old ones if they not used anymore.
They are useful when you do not need to change response data for testing.
In case if you need to test something with using specific responses, you can mock it directly using `add_mock` function from `MockProvider`.


## TODOS
- [ ] run tests marked with possible_integration as a part of integration tests with a real providers
