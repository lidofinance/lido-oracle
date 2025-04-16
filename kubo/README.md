## Kubo distribution for lido-oracle

### Init scripts

Kubo [executes scripts](https://github.com/ipfs/kubo/blob/fd50eb0fc385ec35cc2269646182920849b3c9b5/bin/container_daemon#L53)
found in the `/container-init.d/` in alphabetical order.

#### `./010-set-conf.sh`

- Updates configuration of Kubo node to get determinstic CIDs
- Set ports to expected by the client
- Explicitly activates relay client

#### `./020-pin-cids.sh`

- Fetches the latest CSM CIDs to pin locally from github source
- Pins all the files locally

The script is used to bootstrap CIDs produced by CSM oracle.

CRON job created via entrypoint to make sure the node pins the latest set of CIDs.
