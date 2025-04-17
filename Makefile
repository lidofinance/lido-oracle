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
EXEC_CMD = docker exec -w $(DEV_WORKDIR) -e VIRTUAL_ENV=/opt/venv -it $(DEV_CONTAINER_NAME)

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
	$(EXEC_CMD) bash

ipython: up
	$(EXEC_CMD) ipython

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

# You can use pre-commit with git inside container,
# but if you are using SSH/GPG, you should use local git, even if your development setup in container
precommit-install: up
	$(EXEC_CMD) pre-commit install

# Use ORACLE_MODULE to run specific module, e.g.:
# make run-module ORACLE_MODULE=accounting
run-module: up
	$(EXEC_CMD) python -m src.main $(ORACLE_MODULE)
