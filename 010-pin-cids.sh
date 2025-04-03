#!/bin/env sh

# Mount this file into docker container:
# docker run \
#     -p 4001:4001 -p 4001:4001/udp -p 127.0.0.1:8080:8080 -p 127.0.0.1:5001:5001 \
#     -v ./010-pin-cids.sh:/container-init.d/010-pin-cids.sh \
#     -v ./ipfs:/data/ipfs \
#     ipfs/kubo:latest

set -e

WGET_ARGS="--quiet --no-check-certificate"
GATEWAY=${GATEWAY:-https://ipfs.io}

echo "Fetching list of CIDs to pin"

LIST=$(mktemp)
trap "rm $LIST" EXIT

wget https://raw.githubusercontent.com/lidofinance/csm-rewards/refs/heads/artifact/cids -O$LIST $WGET_ARGS

echo "Bootstrap pinned CIDs"
while IFS= read -r cid; do
  {
    ipfs pin add ${cid} && continue || echo "Fetching ${cid} from remote"

    FILE=$(mktemp)
    wget $GATEWAY/ipfs/${cid} -O$FILE $WGET_ARGS
    ipfs add $FILE && rm $FILE
    ipfs pin add $cid
  }
done < $LIST

echo "CIDs bootstrap complete!"
