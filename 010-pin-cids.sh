#!/bin/sh

# Mount this file into docker container:
# docker run \
#     -p 4001:4001 -p 4001:4001/udp -p 127.0.0.1:8080:8080 -p 127.0.0.1:5001:5001 \
#     -v ./010-pin-cids.sh:/container-init.d/010-pin-cids.sh \
#     -v ./ipfs:/data/ipfs \
#     ipfs/kubo:latest

set -e

GATEWAY=${GATEWAY:-https://ipfs.io}

echo "Fetching list of CIDs to pin"
LIST=$(mktemp)
wget https://raw.githubusercontent.com/lidofinance/csm-rewards/refs/heads/artifact/cids -O$LIST

echo "Bootstrap pinned CIDs"
while IFS= read -r cid; do
  {
    set -x
    ipfs pin add $cid && continue

    FILE=$(mktemp)
    wget $GATEWAY/ipfs/$cid -O$FILE --no-check-certificate
    ipfs add $FILE && rm $FILE
    ipfs pin add $cid
  }
done < $LIST
rm $LIST
