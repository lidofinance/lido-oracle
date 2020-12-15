#!/bin/bash
set -e +u
set -o pipefail

IMG="lidofinance/oracle:latest"
export DOCKER_CONFIG=$HOME/.lidofinance

#### Version info ####
if ! python ./helpers/get_git_info.py > ./version.json; then
  echo "python script error"
  exit 1
fi

#### Show info ####

echo "version: $(cat ./version.json | jq --raw-output .version)"
echo "commit hash: $(cat ./version.json | jq --raw-output .commit_hash)"
echo "commit message: $(cat ./version.json | jq --raw-output .commit_message)"
echo "commit datetime: $(cat ./version.json | jq --raw-output .commit_datetime)"
echo "build datetime: $(cat ./version.json | jq --raw-output .build_datetime)"
echo "tags: $(cat ./version.json | jq --raw-output .tags)"
echo "branch: $(cat ./version.json | jq --raw-output .branch)"

echo "Building oracle Docker image..."
docker build \
  --build-arg VERSION="$(cat ./version.json | jq --raw-output .version)" \
  --build-arg COMMIT_MESSAGE="$(cat ./version.json | jq --raw-output .commit_message)" \
  --build-arg COMMIT_HASH="$(cat ./version.json | jq --raw-output .commit_hash)" \
  --build-arg COMMIT_DATETIME="$(cat ./version.json | jq --raw-output .commit_datetime)" \
  --build-arg BUILD_DATETIME="$(cat ./version.json | jq --raw-output .build_datetime)" \
  --build-arg TAGS="$(cat ./version.json | jq --raw-output .tags)" \
  --build-arg BRANCH="$(cat ./version.json | jq --raw-output .branch)" \
  -t $IMG \
  .
echo "The image \"${IMG}\" was built"

case "$PUSH" in
    "1")
    echo "Pushing image to the Docker Hub"
    docker push $IMG
    ;;
    "0"|"")
    echo "Skip pushing the image to the Docker Hub"
    ;;    *)   # unknown
    echo "unknown value, PUSH=\"${PUSH}\""
    exit 1
    ;;
esac
