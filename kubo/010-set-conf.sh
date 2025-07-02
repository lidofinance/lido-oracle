#!/bin/env sh

set -eu

ipfs config --json Import.CidVersion 0
ipfs config --json Import.UnixFSRawLeaves false
ipfs config Import.UnixFSChunker size-262144
ipfs config Import.HashFunction sha2-256

ipfs config Addresses.Gateway /ip4/0.0.0.0/tcp/$GATEWAY_PORT
ipfs config Addresses.API /ip4/0.0.0.0/tcp/$API_PORT

ipfs config --json Swarm.RelayService.Enabled false
ipfs config --json Swarm.RelayClient.Enabled true
