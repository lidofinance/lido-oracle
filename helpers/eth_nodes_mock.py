import json
from time import sleep
from aiohttp import web
from eth_abi.codec import ABICodec
from web3._utils.abi import build_default_registry

routes = web.RouteTableDef()

with open('tests/responses.json', 'r') as file:
    responses = json.loads(file.read())

lighthouse_responses = responses['lighthouse']
prysm_responses = responses['prysm']


@routes.get('/mock/set/{beacon}')
async def set_beacon(request):
    beacon = int(request.match_info['beacon'])
    if beacon == 1:
        request.app['lighthouse'] = True
        request.app['prysm'] = not request.app['lighthouse']
        print('mock set to Lighthouse')
        return web.json_response('mock set to Lighthouse')
    else:
        request.app['prysm'] = True
        request.app['lighthouse'] = not request.app['prysm']
        print('mock set to Prysm')
        return web.json_response('mock set to Prysm')


@routes.get('/eth/v1/node/version')
async def beacon_ver(request):
    if request.app['lighthouse']:
        return web.json_response(lighthouse_responses['version'])
    return web.json_response('404: Not Found')


@routes.get('/eth/v1/beacon/states/head/finality_checkpoints')
async def beacon_cp(request):
    if request.app['lighthouse']:
        return web.json_response(lighthouse_responses['finalized_epoch'])
    return web.json_response('404: Not Found')


@routes.get('/eth/v1/beacon/states/9120/validators')
async def validators_lighthouse(request):
    if request.app['lighthouse']:
        return web.json_response(lighthouse_responses['validators'])
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
    elif req['method'] == 'web3_clientVersion':
        pass
    elif req['method'] == 'eth_gasPrice':
        resp["result"] = '0x3b9aca00'
    elif req['method'] == 'eth_getTransactionCount':
        resp["result"] = '0x2'
    elif req['method'] == 'eth_sendRawTransaction':
        resp["result"] = '0x2'
    elif req['method'] == 'eth_getTransactionReceipt':
        resp['result'] = {"blockHash": "0xa3a679373fa4f98bb4bd638042f2550ecff5171194a1a9d132a6d7237b50fe0d", "blockNumber": "0x1079", "contractAddress": None, "cumulativeGasUsed": "0x18d3c", "from": "0x656e544deab532e9f5b8b8079b3809aa1757fb0d", "gasUsed": "0x18d3c", "logs": [
        ], "logsBloom": "0x00000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000", "status": "0x1", "to": "0xcd3db5ca818a645359e09543cc0e5b7bb9593229", "transactionHash": "0x4624ea5e5f8512a994abf68a5999bc921bd47cafec48920f58306b5c3afefda3", "transactionIndex": "0x0"}
    elif req['method'] == 'eth_call':
        if req['params'][0]['data'] == '0x833b1fce':  # getOracle
            resp["result"] = "0x000000000000000000000000cd3db5ca818a645359e09543cc0e5b7bb9593229"
        elif req['params'][0]['data'] == '0x27a099d8':  # getOperators
            resp["result"] = "0x0000000000000000000000007faf80e96530e5cd13a1f35701fcc6b334b2fd75"
        elif req['params'][0]['data'] == '0xe547c77c':  # getBeaconSpec
            resp["result"] = "0x000000000000000000000000000000000000000000000000000000000000001400000000000000000000000000000000000000000000000000000000000000080000000000000000000000000000000000000000000000000000000000000001000000000000000000000000000000000000000000000000000000005fcbcdd0"
        elif req['params'][0]['data'] == '0xae2e3538':  # getBeaconStat
            resp["result"] = "0x0000000000000000000000000000000000000000000000000000000000000003000000000000000000000000000000000000000000000000000000000000000300000000000000000000000000000000000000000000003bd3ddd3b714c00800"
        elif req['params'][0]['data'] == '0x47b714e0':  # getBufferedEther
            resp["result"] = "0x00000000000000000000000000000000000000000000000176b344f2a78c0000"
        elif req['params'][0]['data'] == '0x72f79b13':  # getCurrentFrame
            resp["result"] = "0x0000000000000000000000000000000000000000000000000000000000000474000000000000000000000000000000000000000000000000000000005fcbf170000000000000000000000000000000000000000000000000000000005fcbf20f"
        elif req['params'][0]['data'] == '0xa70c70e4':  # getNodeOperatorsCount
            resp["result"] = "0x0000000000000000000000000000000000000000000000000000000000000000"  # fixme, count == 0
        elif req['params'][0]['data'] == '0xdb9887ea0000000000000000000000000000000000000000000000000000000000000000':
            resp["result"] = "0x0000000000000000000000000000000000000000000000000000000000000000"
        elif req['params'][0]['data'] == '0xb449402a00000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000':
            resp["result"] = "0x000000000000000000000000000000000000000000000000000000000000006000000000000000000000000000000000000000000000000000000000000000c0000000000000000000000000000000000000000000000000000000000000000100000000000000000000000000000000000000000000000000000000000000308e7ebb0d21a59d2197c0d42fecb115fade630873995db96830174efbc5f2ab26fa6d1e5d2725738e2870c311e852e89d000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000060a25beab0a9f2077f97e4b3244362b3b71f533287d76fd5c74d862130f4951a6af5aff74e15298074ba05946e8526bf3b116658f001890ecfe440ac576e84dede95ff80c478695606eb7e315c25731c14b0c9330cd49108b5df5e833d1f24db21"
        elif req['params'][0]['data'] == '0xa70c70e4':  # fixme duplicated (see above)
            resp["result"] = "0x00000000000000000000000000000000000000000000000176b344f2a78c0000"
        elif req['params'][0]['data'] == '0x37cfdaca':
            resp["result"] = "0x00000000000000000000000000000000000000000000003d4a9118a9bc4c0800"
        elif req['params'] == [{'to': '0xA5d26F68130c989ef3e063c9bdE33BC50a86629D', 'data': '0x56396715'}, 'latest']:  # withdrawal_credentials
            resp["result"] = "0x009690e5d4472c7c0dbdf490425d89862535d2a52fb686333f3a0a9ff5d2125e"
            codec = ABICodec(build_default_registry())
            # codec.decode_abi(output_types, return_data)
            resp["result"] = codec.encode_abi(['bytes'], [
                b'\x00\x96\x90\xe5\xd4G,|\r\xbd\xf4\x90B]\x89\x86%5\xd2\xa5/\xb6\x863?:\n\x9f\xf5\xd2\x12^']).hex()
            # resp["result"] = "0x0000000000000000000000000000000000000000000000000000000000000001"  # withdrawal_credentials
            # resp["result"] = b'\x00\x96\x90\xe5\xd4G,|\r\xbd\xf4\x90B]\x89\x86%5\xd2\xa5/\xb6\x863?:\n\x9f\xf5\xd2\x12^'  # withdrawal_credentials
        elif 'gas' in req['params'][0].keys():
            resp["result"] = "0x"
        else:
            print("Unknown request {req}")
        print(f"Response: {resp}")
    elif req['method'] == 'eth_getBlockByNumber':
        resp['result'] = {"difficulty":"0x1","extraData":"0x0000000000000000000000000000000000000000000000000000000000000000c708ff3b6eb7a8ec7e468487caf4473d2095164805c24b7f3465acaa526a306862fe89c1005297b3fc70262c0e996cd2c4d7156f3e2f1245f649a579753e598100","gasLimit":"0x7a1200","gasUsed":"0x18d2d2","hash":"0x37d8e5ddb9e7974e8fe3f19c5593f70bc485e58c4d1c41aef58415251d9aac2d","logsBloom":"0x00300080000000000000000281100082188000500800020001010000408090040801000021000220000025e00004001008004000000040a0000062000204040202200000040180000000000818000020000c0004000023400004000080400000081010000208002002820002000088000000004000000000020004100000000000000102040000000050000200000000000002011001000800010040080400000c800000080200102000000000200000000000010400014100001000000001000000400300190010400000000440000a000012000040001014000000000020000000020000000000000000000c00000000008000000800420802000000c02004","miner":"0x0000000000000000000000000000000000000000","mixHash":"0x0000000000000000000000000000000000000000000000000000000000000000","nonce":"0x0000000000000000","number":"0x3ba085","parentHash":"0x1822e9dc27c141d92ee0b156e7fa81ec24d975758a32fc1e799292883edc8f43","receiptsRoot":"0x8e783f9730dcfed65da8d9d14985da84f59266d4ea5e2ce01d43800eaf5e97a1","sha3Uncles":"0x1dcc4de8dec75d7aab85b567b6ccd41ad312451b948a7413f0a142fd40d49347","size":"0xa01","stateRoot":"0x5752f34dccc5b6b2cc6ad9e4bad33bacae451d529a03fead33ef04edc4d9ffb4","timestamp":"0x5fd36085","totalDifficulty":"0x575a15","transactions":["0x706bc1f243edf2775e99b7ea181a989ce7b4161a1d200bfd01672fd192d3f85f","0xe45526b1508025bbf9287885464d0986542f0add2c695b41d61973e5ad318d8d","0xc7e9472892cccab85fedc9356ba91af44d4f599a9f7477b965ea72d90681f9ec","0x51e3faa1d8951c54e65c760cadc3cec1086de284b32b3614301b778d501358ee","0xfa685b3b44e6b2145670a1984503c0c22adf5ec82d83b9c2417e88fc4c5f6b31","0x66da670b37601b08753aaa3ba9b8690bc6c2511a656ffd496829b0e2009408a4"],"transactionsRoot":"0x2c809b6072a404fcbe8580d8fc37f6579be6d146a52218cb97cd1ceca036ab16","uncles":[]}
    elif req['method'] == 'eth_getLogs':
        resp['result'] = [{'address': '0xcd3db5ca818a645359e09543cc0e5b7bb9593229', 'topics': ['0x95423529aa0b2867e02676b0bb4766cde576fb31ea77056f683bc236c7c15f9d'], 'data': '0x0000000000000000000000000000000000000000000000000000000000003E800000000000000000000000000000000000000000000003bd3ddd3b714c008000000000000000000000000000000000000000000000000000000000000000003', 'blockNumber': '0x32a64', 'transactionHash': '0x812a5955e060b7d377ffa0a0046782810dd975abac9c0a94c6819854192ef119', 'transactionIndex': '0x0', 'blockHash': '0xabc9aa063a7e94ae30daf47dc64e8bccea7a0a81ff6423797866a86b660e2fea', 'logIndex': '0x0', 'removed': False}]
    elif req['method'] == 'eth_getBlockByHash':
        resp['result'] = {"difficulty": "0x2", "extraData": "0xd883010919846765746888676f312e31352e35856c696e757800000000000000449bddee2636a0554442001fd4ef258d590ad7531d944a2ff5334ea53cfd254c3f5caa0cbeba09ec41bb963e6ea94f68c49d86ca4f20b6ee003634656d8dcce500", "gasLimit": "0x7a1200", "gasUsed": "0x6fbc6", "hash": "0xabc9aa063a7e94ae30daf47dc64e8bccea7a0a81ff6423797866a86b660e2fea", "logsBloom": "0x00000000000000000000000040000000000000000000000000000000000000000000200000000100000000000000000000000000000000000000000000000000000000001000000000000008000000000000000001000040000000001200000400000000000000000000000004000000000000000000000000000010000001000000000000020000000008000008000400000000000000000000001000000000000800000000000000000000010000000000000000000000000000000000000000000002012000000008000000000000000000000000000000000000000000000000000000000000000200000000000000000000001000000000008000000000", "miner": "0x0000000000000000000000000000000000000000", "mixHash": "0x0000000000000000000000000000000000000000000000000000000000000000", "nonce": "0x0000000000000000", "number": "0x32a64", "parentHash": "0xb1534e9f3394f6f7bf846a593724b9e4ca73c92fd75e92b60808b562909c3cd3", "receiptsRoot": "0x415869fc87ad81732266f527ea5ae79b44d7914620af3d82d32e8c2b693a4150", "sha3Uncles": "0x1dcc4de8dec75d7aab85b567b6ccd41ad312451b948a7413f0a142fd40d49347", "size": "0x334", "stateRoot": "0x5d73eb4759b9c57925148dc8599f31cfbda0f284b084525c1288b298390f5771", "timestamp": "0x5fc952b7", "totalDifficulty": "0x654c9", "transactions": ["0x812a5955e060b7d377ffa0a0046782810dd975abac9c0a94c6819854192ef119"], "transactionsRoot": "0xf7b548ef7f8f13bff5ed8a74c955b76dc33597a6dffe2ff062738e528fcf41a0", "uncles": []}

    return web.json_response(resp)


def main(argv):
    app = web.Application()
    app['lighthouse'] = True
    app['prysm'] = not app['lighthouse']
    app.add_routes(routes)
    web.run_app(app)
    return app
