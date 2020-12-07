#!/bin/sh
export ETH1_NODE=http://127.0.0.1:8080
export BEACON_NODE=http://127.0.0.1:8080
export POOL_CONTRACT=0xdead00000000000000000000000000000000beef
export PYTHONPATH=app/
export MEMBER_PRIV_KEY=0xdeadbeef000000000000000000000000000000000000000000000000deadbeef

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
python -m aiohttp.web -H localhost -P 8080 helpers.eth_nodes_mock:main > /dev/null 2>&1 &

if [ "${LIGHTHOUSE}" = 1 ]
then
    echo "Switch mock to Lighthouse"
    curl http://127.0.0.1:8080/mock/set/1
    echo "Run python tests"
    pytest
    CODE=$?
    if [ ${CODE} -ne 0 ]
    then
        echo "Lighthouse test failed"
        lsof -t -i tcp:8080 | xargs kill -9
        exit ${CODE}
    fi
fi

if [ "${PRYSM}" = 1 ]
then
    echo "Switch mock to Prysm"
    curl http://127.0.0.1:8080/mock/set/2
    pytest
    CODE=$?
    if [ ${CODE} -ne 0 ]
    then
        echo "Prysm test failed"
        lsof -t -i tcp:8080 | xargs kill -9
        exit ${CODE}
    fi
fi

echo "Stop ETH1/ETH2 mock webservice and exit"
# Kill all child process
pkill -P $$
