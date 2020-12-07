#!/bin/bash
source ./.env
set -e +u
set -o pipefail

IMG="lidofinance/oracle:latest"
export DOCKER_CONFIG=$HOME/.lidofinance

commit_short_hash=$(git log -1 --format=%h)
commit_datetime=$(git show -s --format=%ci $commit_short_hash)
#commit_date=$(echo $commit_datetime | awk '{print $1}')
commit_tags_newline_separated="$(git tag --points-at HEAD)"
if [ -z "${commit_tags_newline_separated}" ]; then
    commit_tags_newline_separated="None"
fi
commit_tags_space_separated=$(echo $commit_tags_newline_separated | tr '\r\n' ' ')
commit_branch=$(git branch --show-current)
if [ -z "${commit_branch}" ]; then
    commit_branch="None"
fi
version=$(python3 helpers/git_top_semver_tag.py)

echo "Version: $version"
echo "Datetime: $commit_datetime"
echo "Message: "
echo "Tags: $commit_tags_space_separated"
echo "Branch: $commit_branch"

echo "Building oracle Docker image..."
docker build -t $IMG --build-arg VERSION=$version --build-arg DATETIME=$commit_datetime --build-arg TAGS="$commit_tags_space_separated" --build-arg BRANCH="$commit_branch" .

echo "Pushing image to the Docker Hub"
docker push $IMG
