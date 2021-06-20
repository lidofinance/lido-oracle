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

if [ $# -eq 0 ]
then
    echo "Performing all tests"
    LIGHTHOUSE=1
    PRYSM=1
fi

BEACON=$(echo "$1" | tr  '[:upper:]' '[:lower:]')

if [ "${BEACON}" = "lighthouse" ]
then
    LIGHTHOUSE=1
fi

if [ "${BEACON}" = "prysm" ]
then
    PRYSM=1
fi

echo "Run ETH1/ETH2 mock webservice"
python3 -m aiohttp.web -H localhost -P ${PORT} helpers.eth_nodes_mock:main > /dev/null 2>&1 &
#sleep 1

if [ "${LIGHTHOUSE}" = 1 ]
then
    echo "Switch mock to Lighthouse"
    curl -s http://127.0.0.1:${PORT}/mock/set/1
    echo "Run python tests"
    pytest
    CODE=$?
    if [ ${CODE} -ne 0 ]
    then
        echo "Lighthouse test failed"
        lsof -t -i tcp:${PORT} | xargs kill -9
        exit ${CODE}
    fi
fi

if [ "${PRYSM}" = 1 ]
then
    echo "Switch mock to Prysm"
    curl -s http://127.0.0.1:${PORT}/mock/set/2
    pytest
    CODE=$?
    if [ ${CODE} -ne 0 ]
    then
        echo "Prysm test failed"
        lsof -t -i tcp:${PORT} | xargs kill -9
        exit ${CODE}
    fi
fi

echo "Stop ETH1/ETH2 mock webservice and exit"
rm -f ${TMP_FILE}
# Kill all child process
pkill -P $$
