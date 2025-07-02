reproducible-build-oracle:
	docker buildx rm oracle-buildkit || true
	docker volume rm $(shell docker volume ls -q --filter name=buildx_buildkit_oracle-buildkit) || true
	docker buildx create --name oracle-buildkit --use || true
	docker buildx use oracle-buildkit
	docker buildx build \
		--platform linux/amd64 \
		--build-arg SOURCE_DATE_EPOCH=0 \
		--no-cache \
		--output type=docker,name=oracle-reproducible-container:local,rewrite-timestamp=true \
		-t oracle-reproducible-container:local \
		.
	docker image inspect oracle-reproducible-container:local --format 'Image hash: {{.Id}}'

DEV_CONTAINER_NAME = oracle-dev-container
DEV_IMAGE = lidofinance/oracle:dev
DEV_WORKDIR = /app
EXEC_CMD = docker exec -w $(DEV_WORKDIR) -e VIRTUAL_ENV=/opt/venv $(DEV_CONTAINER_NAME)
EXEC_CMD_INTERACTIVE = docker exec -w $(DEV_WORKDIR) -e VIRTUAL_ENV=/opt/venv -it $(DEV_CONTAINER_NAME)

up:
	@if [ -z "$$(docker ps -q -f name=$(DEV_CONTAINER_NAME))" ]; then \
		echo "No container found, starting..."; \
		docker build --target development -t $(DEV_IMAGE) .; \
		docker run -dit --env-file .env --name $(DEV_CONTAINER_NAME) -v $(shell pwd):$(DEV_WORKDIR) $(DEV_IMAGE) bash; \
	else \
		echo "Container $(DEV_CONTAINER_NAME) already running"; \
	fi

rebuild:
	@echo "Rebuilding dev image and container..."
	docker build --no-cache --target development -t $(DEV_IMAGE) .; \
	if [ -n "$$(docker ps -q -f name=$(DEV_CONTAINER_NAME))" ]; then \
		echo "Stopping and removing existing container..."; \
		docker stop $(DEV_CONTAINER_NAME) && docker rm $(DEV_CONTAINER_NAME); \
	fi; \
	$(MAKE) up

sh: up
	$(EXEC_CMD_INTERACTIVE) bash

ipython: up
	$(EXEC_CMD_INTERACTIVE) ipython

poetry-lock: up
	$(EXEC_CMD) poetry lock --no-update

lint: up
	$(EXEC_CMD) black tests
	$(EXEC_CMD) pylint src tests --jobs=2
	$(EXEC_CMD) mypy src

# Use ORACLE_TEST_PATH to run specific tests, e.g.:
# make test ORACLE_TEST_PATH=tests/providers_clients/test_keys_api_client.py
test: up
	$(EXEC_CMD) pytest $(ORACLE_TEST_PATH)

# Use ORACLE_MODULE to run specific module, e.g.:
# make run-module ORACLE_MODULE=accounting
run-module: up
	$(EXEC_CMD) python -m src.main $(ORACLE_MODULE)

install-pre-commit:
	@echo "Creating pre-commit hook..."
	@echo '#!/bin/sh' > .git/hooks/pre-commit
	@echo '# Auto-generated pre-commit hook' >> .git/hooks/pre-commit
	@echo 'make lint' >> .git/hooks/pre-commit
	@echo 'if [ $$? -ne 0 ]; then' >> .git/hooks/pre-commit
	@echo '    echo "Linting failed!"' >> .git/hooks/pre-commit
	@echo '    exit 1' >> .git/hooks/pre-commit
	@echo 'fi' >> .git/hooks/pre-commit
	@echo 'make test' >> .git/hooks/pre-commit
	@echo 'if [ $$? -ne 0 ]; then' >> .git/hooks/pre-commit
	@echo '    echo "Tests failed!"' >> .git/hooks/pre-commit
	@echo '    exit 1' >> .git/hooks/pre-commit
	@echo 'fi' >> .git/hooks/pre-commit
	@chmod +x .git/hooks/pre-commit
	@echo "Pre-commit hook installed successfully"
