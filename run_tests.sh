#!/bin/sh
export PORT=${PORT:-8080}
export WEB3_PROVIDER_URI=http://127.0.0.1:${PORT}
export BEACON_NODE=http://127.0.0.1:${PORT}
export POOL_CONTRACT=0xdead00000000000000000000000000000000beef
export PYTHONPATH=app/
export MEMBER_PRIV_KEY=0xdeadbeef000000000000000000000000000000000000000000000000deadbeef
export PROMETHEUS_METRICS_PORT=$((PORT+1))
export STETH_CURVE_POOL_CONTRACT=0xdead00000000000000000000000000000000beef
export STETH_PRICE_ORACLE_CONTRACT=0xdead00000000000000000000000000000000beef
TMP_FILE='/tmp/test-version.json'

BEACON="lighthouse"
LIGHTHOUSE=1

echo "Run ETH1/ETH2 mock webservice"
python -m aiohttp.web -H localhost -P ${PORT} helpers.eth_nodes_mock:main > /dev/null 2>&1 &
#sleep 1
curl -s http://127.0.0.1:${PORT}/mock/set/1
echo "Run python tests"
poetry run pytest
CODE=$?
if [ ${CODE} -ne 0 ]
then
    echo "Lighthouse test failed"
    lsof -t -i tcp:${PORT} | xargs kill -9
    exit ${CODE}
fi

echo "Stop ETH1/ETH2 mock webservice and exit"
rm -f ${TMP_FILE}
# Kill all child process
pkill -P $$
