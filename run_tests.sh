#!/usr/bin/env bash
export ETH1_NODE=http://127.0.0.1:8080
export BEACON_NODE=http://127.0.0.1:8080
export POOL_CONTRACT=0xdead00000000000000000000000000000000beef
export PYTHONPATH=app/
export MEMBER_PRIV_KEY=0xdeadbeef000000000000000000000000000000000000000000000000deadbeef
echo "Run ETH1/ETH2 mock webservice"
python -m aiohttp.web -H localhost -P 8080 helpers.eth_nodes_mock:main &> /dev/null &
sleep 1
ETH_MOCK_PID=$!
echo "Run python tests"
pytest
echo "Stop ETH1/ETH2 mock webservice and exit"
kill $ETH_MOCK_PID

