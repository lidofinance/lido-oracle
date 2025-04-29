#!/bin/env sh

set -eu

WGET_ARGS="--quiet --no-check-certificate"
GATEWAY=${GATEWAY:-https://ipfs.io}

echo "Fetching list of CIDs to pin"

LIST=$(mktemp)
trap "rm $LIST" EXIT

wget https://raw.githubusercontent.com/lidofinance/csm-rewards/refs/heads/$CHAIN/cids -O$LIST $WGET_ARGS

echo "Bootstrap pinned CIDs"
while IFS= read -r cid; do
  {
    ipfs pin add ${cid} && continue || echo "Fetching ${cid} from remote"

    FILE=$(mktemp)
    trap "rm $FILE" EXIT

    wget $GATEWAY/ipfs/${cid} -O$FILE $WGET_ARGS

    imported_cid=$(ipfs add -q $FILE)
    [ $imported_cid != $cid ] && { echo "Error: Importing $cid, but got $imported_cid"; exit 1; }
  }
done < $LIST

echo "CIDs bootstrap complete!"
