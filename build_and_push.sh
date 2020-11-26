#!/bin/bash
source ./.env
set -e +u
set -o pipefail

IMG="lidofinance/oracle:latest"
export DOCKER_CONFIG=$HOME/.lidofinance

echo "Building oracle Docker image..."
docker build -t $IMG .

echo "Pushing image to the Docker Hub"
docker push $IMG
