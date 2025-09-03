## Setup

There are two ways to run the project locally for development:
1. Using Docker  
2. Directly on the host system

Using Docker allows you to develop in an environment that closely mirrors production, while also providing an extra layer of system security.

### Docker

1. Install Docker  
2. Run the command `make up` to build the image and start the container. (`make` is likely already installed on your system as a standard build tool on Unix-like environments. If not, you can [download it here](https://www.gnu.org/software/make/).)  
3. Run `make install-pre-commit` to install pre-commit hooks. The hook will be installed on your host machine, but tests and linting will run inside the container.

You can find the full list of available Make commands [here](https://github.com/lidofinance/lido-oracle/blob/develop/Makefile).

### Local Setup

1. [Install Poetry](https://python-poetry.org/docs/#installation)  
2. Install the project dependencies:

```bash
poetry install
```

3. Install pre-commit hooks

```bash
poetry run pre-commit install
```

## Startup

Required variables for accounting and ejector modules

```bash
export EXECUTION_CLIENT_URI=...
export CONSENSUS_CLIENT_URI=...
export KEYS_API_URI=...
export LIDO_LOCATOR_ADDRESS=...
```

Required variables for CSM module

```bash
export EXECUTION_CLIENT_URI=...
export CONSENSUS_CLIENT_URI=...
export KEYS_API_URI=...
export LIDO_LOCATOR_ADDRESS=...
export CSM_MODULE_ADDRESS=...
export MAX_CYCLE_LIFETIME_IN_SECONDS=60000  # Reasonable high value to make sure the oracle has enough time to process the whole frame.
```

### Run oracle module

#### Docker
```bash
make run-module ORACLE_MODULE=<module>
```
#### Local setup
```bash
poetry run python -m src.main <module>
```

Where `<module>` is one of:

- `accounting`
- `ejector`
- `csm`
- `check`

## Code quality

Used the following tools:

- [black](https://github.com/psf/black)
- [pylint](https://github.com/pylint-dev/pylint/)
- [mypy](https://github.com/python/mypy/)
  See the [configuration](pyproject.toml) for details for each linter.

Make sure that your code is formatted correctly and passes all checks:

#### Docker
```bash
make lint
```

#### Local setup
```bash
black tests
pylint src tests
mypy src
```

## Tests
[Testing guide](testing.md)
#### Docker
```bash
make test
```

#### Local setup
```bash
poetry run pytest tests
```
