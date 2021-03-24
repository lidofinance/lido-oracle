#!/bin/bash
set +u
set -o pipefail

if [[ -z "${TAG}" ]] ; then
  echo "no TAG env provided. Using default \"latest\"."
  TAG="latest"
else
  echo "TAG=${TAG} (from env)"
fi


IMG="lidofinance/oracle:${TAG}"
export DOCKER_CONFIG=$HOME/.lidofinance

#### Version info ####
META_INFO=$(python ./helpers/get_git_info.py 2>&1)

if [[ $? != 0 ]]
then
    echo "ERROR: python script get_git_info.py"
    echo "$META_INFO"
    META_INFO=""
else
    #### Show info ####
    echo "version: $(echo ${META_INFO} | jq --raw-output .version)"
    echo "commit hash: $(echo ${META_INFO}| jq --raw-output .commit_hash)"
    echo "commit message: $(echo ${META_INFO} | jq --raw-output .commit_message)"
    echo "commit datetime: $(echo ${META_INFO}| jq --raw-output .commit_datetime)"
    echo "build datetime: $(echo ${META_INFO}| jq --raw-output .build_datetime)"
    echo "tags: $(echo ${META_INFO} | jq --raw-output .tags)"
    echo "branch: $(echo ${META_INFO} | jq --raw-output .branch)"
fi

echo "Building oracle Docker image ${IMG}..."
docker build \
  --build-arg VERSION="$(echo ${META_INFO} | jq --raw-output .version)" \
  --build-arg COMMIT_MESSAGE="$(echo ${META_INFO} | jq --raw-output .commit_message)" \
  --build-arg COMMIT_HASH="$(echo ${META_INFO} | jq --raw-output .commit_hash)" \
  --build-arg COMMIT_DATETIME="$(echo ${META_INFO} | jq --raw-output .commit_datetime)" \
  --build-arg BUILD_DATETIME="$(echo ${META_INFO} | jq --raw-output .build_datetime)" \
  --build-arg TAGS="$(echo ${META_INFO} | jq --raw-output .tags)" \
  --build-arg BRANCH="$(echo ${META_INFO} | jq --raw-output .branch)" \
  -t ${IMG} \
  .
echo "The image \"${IMG}\" was built"

case "${PUSH}" in
    "1")
    echo "Pushing image to the Docker Hub"
    docker push ${IMG}
    ;;
    "0"|"")
    echo "Skip pushing the image to the Docker Hub"
    ;;    *)   # unknown
    echo "unknown value, PUSH=\"${PUSH}\""
    exit 1
    ;;
esac
