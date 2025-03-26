reproducible-build-oracle:
	docker buildx rm oracle-buildkit || true
	docker buildx create --name oracle-buildkit --use || true
	docker buildx use oracle-buildkit
	docker buildx build \
		--build-arg SOURCE_DATE_EPOCH=$(shell git log -1 --pretty=%ct) \
		--no-cache \
		--output type=docker,name=oracle-reproducible-container:local,rewrite-timestamp=true \
		-t oracle-reproducible-container:local \
		.
	docker image inspect oracle-reproducible-container:local --format 'Image hash: {{.Id}}'
