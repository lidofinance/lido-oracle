import json
from time import sleep
from aiohttp import web

routes = web.RouteTableDef()

with open('tests/responses.json', 'r') as file:
    responses = json.loads(file.read())

lighthouse_responses = responses['lighthouse']
prysm_responses = responses['prysm']


@routes.get('/mock/set/{beacon}')
async def set_beacon(request):
    beacon = int(request.match_info['beacon'])
    if beacon == 1:
        request.app['ligthouse'] = True
        request.app['prysm'] = not request.app['ligthouse']
        print('mock set to Lighthouse')
        return web.json_response('mock set to Lighthouse')
    else:
        request.app['prysm'] = True
        request.app['ligthouse'] = not request.app['prysm']
        print('mock set to Prysm')
        return web.json_response('mock set to Prysm')


@routes.get('/eth/v1/node/version')
async def beacon_ver(request):
    if request.app['ligthouse']:
        return web.json_response(lighthouse_responses['version'])
    return web.json_response('404: Not Found')


@routes.get('/eth/v1/beacon/states/head/finality_checkpoints')
async def beacon_cp(request):
    if request.app['ligthouse']:
        return web.json_response(lighthouse_responses['finalized_epoch'])
    return web.json_response('404: Not Found')


@routes.get('/eth/v1alpha1/node/version')
async def prysm_ver(request):
    if request.app['prysm']:
        return web.json_response(prysm_responses['version'])
    return web.json_response('404: Not Found')


@routes.get('/eth/v1alpha1/beacon/chainhead')
async def beacon_prysm__cp(request):
    if request.app['prysm']:
        return web.json_response(prysm_responses['head'])
    return web.json_response('404: Not Found')


@routes.get('/eth/v1alpha1/validators/balances')
async def validators_prysm(request):
    if request.app['prysm']:
        return web.json_response(prysm_responses['validators'])
    return web.json_response('404: Not Found')


@routes.post('/')
async def eth1(request):
    req = await request.json()
    resp = {}
    if 'jsonrpc' not in req:
        raise Exception("It's not a JSON PRC request")
    resp['jsonrpc'] = req['jsonrpc']
    if 'id' not in req:
        raise Exception("It's not a JSON PRC request")
    resp['id'] = req['id']
    if 'method' not in req:
        raise Exception("It's not a JSON PRC request")
    if 'params' not in req:
        raise Exception("Params are absent")
    print(f"Received ETH1 request: {req}")
    if req['method'] == 'eth_chainId':
        resp["result"] = "0x5"
        print(f"Response: {resp}")
    if req['method'] == 'eth_gasPrice':
        resp["result"] = '0x3b9aca00'
    if req['method'] == 'eth_getTransactionCount':
        resp["result"] = '0x2'
    if req['method'] == 'eth_sendRawTransaction':
        resp["result"] = '0x2'
    if req['method'] == 'eth_getTransactionReceipt':
        resp['result'] = {"blockHash": "0xa3a679373fa4f98bb4bd638042f2550ecff5171194a1a9d132a6d7237b50fe0d", "blockNumber": "0x1079", "contractAddress": None, "cumulativeGasUsed": "0x18d3c", "from": "0x656e544deab532e9f5b8b8079b3809aa1757fb0d", "gasUsed": "0x18d3c", "logs": [
        ], "logsBloom": "0x00000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000", "status": "0x1", "to": "0xcd3db5ca818a645359e09543cc0e5b7bb9593229", "transactionHash": "0x4624ea5e5f8512a994abf68a5999bc921bd47cafec48920f58306b5c3afefda3", "transactionIndex": "0x0"}
    if req['method'] == 'eth_call':
        if req['params'][0]['data'] == '0x833b1fce':
            resp["result"] = "0x000000000000000000000000cd3db5ca818a645359e09543cc0e5b7bb9593229"
        elif req['params'][0]['data'] == '0x27a099d8':
            resp["result"] = "0x0000000000000000000000007faf80e96530e5cd13a1f35701fcc6b334b2fd75"
        elif req['params'][0]['data'] == '0x5aeff123':
            resp["result"] = "0x000000000000000000000000000000000000000000000000000000000000001400000000000000000000000000000000000000000000000000000000000000080000000000000000000000000000000000000000000000000000000000000001000000000000000000000000000000000000000000000000000000005fcbcdd0"
        elif req['params'][0]['data'] == '0x72f79b13':
            resp["result"] = "0x0000000000000000000000000000000000000000000000000000000000000474000000000000000000000000000000000000000000000000000000005fcbf170000000000000000000000000000000000000000000000000000000005fcbf20f"
        elif req['params'][0]['data'] == '0xa70c70e4':
            resp["result"] = "0x0000000000000000000000000000000000000000000000000000000000000000"
        elif req['params'][0]['data'] == '0xdb9887ea0000000000000000000000000000000000000000000000000000000000000000':
            resp["result"] = "0x0000000000000000000000000000000000000000000000000000000000000000"
        elif req['params'][0]['data'] == '0xb449402a00000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000':
            resp["result"] = "0x000000000000000000000000000000000000000000000000000000000000006000000000000000000000000000000000000000000000000000000000000000c0000000000000000000000000000000000000000000000000000000000000000100000000000000000000000000000000000000000000000000000000000000308e7ebb0d21a59d2197c0d42fecb115fade630873995db96830174efbc5f2ab26fa6d1e5d2725738e2870c311e852e89d000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000060a25beab0a9f2077f97e4b3244362b3b71f533287d76fd5c74d862130f4951a6af5aff74e15298074ba05946e8526bf3b116658f001890ecfe440ac576e84dede95ff80c478695606eb7e315c25731c14b0c9330cd49108b5df5e833d1f24db21"
        elif 'gas' in req['params'][0].keys():
            resp["result"] = "0x"
        else:
            print("Unknown request {req}")
        print(f"Response: {resp}")

    return (web.json_response(resp))


def main(argv):
    app = web.Application()
    app['ligthouse'] = True
    app['prysm'] = not app['ligthouse']
    app.add_routes(routes)
    web.run_app(app)
    return app
