import os
import json
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


@routes.get('/eth/v2/beacon/blocks/9120')
async def block_lighthouse(request):
    if request.app['lighthouse']:
        return web.json_response(lighthouse_responses['block_finalized'])
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
        resp['result'] = {
            "blockHash": "0xa3a679373fa4f98bb4bd638042f2550ecff5171194a1a9d132a6d7237b50fe0d",
            "blockNumber": "0x1079",
            "contractAddress": None,
            "cumulativeGasUsed": "0x18d3c",
            "from": "0x656e544deab532e9f5b8b8079b3809aa1757fb0d",
            "gasUsed": "0x18d3c",
            "logs": [],
            "logsBloom": "0x00000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000",
            "status": "0x1",
            "to": "0xcd3db5ca818a645359e09543cc0e5b7bb9593229",
            "transactionHash": "0x4624ea5e5f8512a994abf68a5999bc921bd47cafec48920f58306b5c3afefda3",
            "transactionIndex": "0x0",
        }
    elif req['method'] == 'eth_call':
        if req['params'][0]['data'] == '0x833b1fce':  # getOracle
            resp["result"] = "0x000000000000000000000000cd3db5ca818a645359e09543cc0e5b7bb9593229"
        elif req['params'][0]['data'] == '0x56396715':  # getWithdrawalCredentials
            resp["result"] = "0x010000000000000000000000b9d7934878b5fb9610b3fe8a5e441e8fad7e293f"
        elif req['params'][0]['data'] == '0x27a099d8':  # getOperators
            resp["result"] = "0x0000000000000000000000007faf80e96530e5cd13a1f35701fcc6b334b2fd75"
        elif req['params'][0]['data'] == '0xe547c77c':  # getBeaconSpec
            resp[
                "result"
            ] = "0x000000000000000000000000000000000000000000000000000000000000001400000000000000000000000000000000000000000000000000000000000000080000000000000000000000000000000000000000000000000000000000000001000000000000000000000000000000000000000000000000000000005fcbcdd0"
        elif req['params'][0]['data'] == '0xae2e3538':  # getBeaconStat
            resp[
                "result"
            ] = "0x0000000000000000000000000000000000000000000000000000000000000003000000000000000000000000000000000000000000000000000000000000000300000000000000000000000000000000000000000000003bd3ddd3b714c00800"
        elif req['params'][0]['data'] == '0x47b714e0':  # getBufferedEther
            resp["result"] = "0x00000000000000000000000000000000000000000000000176b344f2a78c0000"
        elif req['params'][0]['data'] == '0x72f79b13':  # getCurrentFrame
            resp[
                "result"
            ] = "0x0000000000000000000000000000000000000000000000000000000000000474000000000000000000000000000000000000000000000000000000005fcbf170000000000000000000000000000000000000000000000000000000005fcbf20f"
        elif req['params'][0]['data'] == '0xa70c70e4':  # getNodeOperatorsCount
            resp["result"] = "0x0000000000000000000000000000000000000000000000000000000000000000"  # fixme, count == 0
        elif req['params'][0]['data'] == '0xdb9887ea0000000000000000000000000000000000000000000000000000000000000000':
            resp["result"] = "0x0000000000000000000000000000000000000000000000000000000000000000"
        elif (
            req['params'][0]['data']
            == '0xb449402a00000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000'
        ):
            resp[
                "result"
            ] = "0x000000000000000000000000000000000000000000000000000000000000006000000000000000000000000000000000000000000000000000000000000000c0000000000000000000000000000000000000000000000000000000000000000100000000000000000000000000000000000000000000000000000000000000308e7ebb0d21a59d2197c0d42fecb115fade630873995db96830174efbc5f2ab26fa6d1e5d2725738e2870c311e852e89d000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000060a25beab0a9f2077f97e4b3244362b3b71f533287d76fd5c74d862130f4951a6af5aff74e15298074ba05946e8526bf3b116658f001890ecfe440ac576e84dede95ff80c478695606eb7e315c25731c14b0c9330cd49108b5df5e833d1f24db21"
        elif req['params'][0]['data'] == '0xa70c70e4':  # fixme duplicated (see above)
            resp["result"] = "0x00000000000000000000000000000000000000000000000176b344f2a78c0000"
        elif req['params'][0]['data'] == '0x37cfdaca':
            resp["result"] = "0x00000000000000000000000000000000000000000000003d4a9118a9bc4c0800"
        elif req['params'] == [
            {'to': '0x1643E812aE58766192Cf7D2Cf9567dF2C37e9B7F', 'data': '0x56396715'},
            'latest',
        ]:  # withdrawal_credentials
            resp["result"] = "0x009690e5d4472c7c0dbdf490425d89862535d2a52fb686333f3a0a9ff5d2125e"
            codec = ABICodec(build_default_registry())
            # codec.decode_abi(output_types, return_data)
            resp["result"] = codec.encode_abi(
                ['bytes'], [b'\x00\x96\x90\xe5\xd4G,|\r\xbd\xf4\x90B]\x89\x86%5\xd2\xa5/\xb6\x863?:\n\x9f\xf5\xd2\x12^']
            ).hex()
            # resp["result"] = "0x0000000000000000000000000000000000000000000000000000000000000001"  # withdrawal_credentials
            # resp["result"] = b'\x00\x96\x90\xe5\xd4G,|\r\xbd\xf4\x90B]\x89\x86%5\xd2\xa5/\xb6\x863?:\n\x9f\xf5\xd2\x12^'  # withdrawal_credentials
        # getQuorum().call()
        elif req['params'] == [{'to': '0xcD3db5ca818a645359e09543Cc0e5b7bB9593229', 'data': '0xc26c12eb'}, 'latest']:
            resp['result'] = '0x0000000000000000000000000000000000000000000000000000000000000001'
        # getOracleMembers().call()
        elif req['params'] == [{'to': '0xcD3db5ca818a645359e09543Cc0e5b7bB9593229', 'data': '0xdabb5757'}, 'latest']:
            resp[
                'result'
            ] = '0x00000000000000000000000000000000000000000000000000000000000000200000000000000000000000000000000000000000000000000000000000000000'
        elif 'gas' in req['params'][0].keys():
            resp["result"] = "0x"
        else:
            print("Unknown request {req}")
        print(f"Response: {resp}")
    elif req['method'] == 'eth_getBlockByNumber':
        resp['result'] = {
            'baseFeePerGas': 216162154845,
            'difficulty': 11328365388145011,
            'extraData': '0x486976656f6e2065752d6865617679',
            'gasLimit': 29970648,
            'gasUsed': 182494,
            'hash': '0x7450ec9242960641bc5787f53a55d6f76cd75d4054ca01567899f5548843d802',
            'logsBloom': '0x00000002000000000000000000000020000000000000000000000000000000000000000000000040000000000000010000000000000020000000000000200000000000000000000800000008000400000000000000000000000000000000000000800200000000000000100000000000000000000000000000000010000800001000000000000000000000000000000000000000000000000001000000100000020000004000000000000080800000000000000000000000080000000002000000000002000000000000000000000000000000000000000000000000000000000010000200000000000000000000000000000000000000000000000400000000',
            'miner': '0x1aD91ee08f21bE3dE0BA2ba6918E714dA6B45836',
            'mixHash': '0x1b2be1373195eb3eefe0fd2443f6c935565ebdcdf8fd1a38d3cc84a15ebc2475',
            'nonce': '0x30da3de3157bf7d6',
            'number': 13667590,
            'parentHash': '0xb26de9c40804f30d8037dd8e131ea68692fb7b9e3c10b3e70f45193a46377a80',
            'receiptsRoot': '0xf90d30245619aabc3a912fc2e181fc96c0ce5a047dce569601000e34d026579d',
            'sha3Uncles': '0x1dcc4de8dec75d7aab85b567b6ccd41ad312451b948a7413f0a142fd40d49347',
            'size': 2395,
            'stateRoot': '0x403a7f42af67e54c1aba1948cdb188b6235aed20bc78c843f16281a39ebb5e5e',
            'timestamp': 1637625884,
            'totalDifficulty': 35008780163466876178638,
            'transactions': [],
            'transactionsRoot': '0x364075b2192d3b9d794b66c156b12361f94e6857f622c8458a0202db31c42551',
            'uncles': [],
        }
    elif req['method'] == 'eth_maxPriorityFeePerGas':
        resp['result'] = 10
    elif req['method'] == 'eth_getLogs':
        resp['result'] = [
            {
                'address': '0xcd3db5ca818a645359e09543cc0e5b7bb9593229',
                'topics': ['0x95423529aa0b2867e02676b0bb4766cde576fb31ea77056f683bc236c7c15f9d'],
                'data': '0x0000000000000000000000000000000000000000000000000000000000003E800000000000000000000000000000000000000000000003bd3ddd3b714c008000000000000000000000000000000000000000000000000000000000000000003',
                'blockNumber': '0x32a64',
                'transactionHash': '0x812a5955e060b7d377ffa0a0046782810dd975abac9c0a94c6819854192ef119',
                'transactionIndex': '0x0',
                'blockHash': '0xabc9aa063a7e94ae30daf47dc64e8bccea7a0a81ff6423797866a86b660e2fea',
                'logIndex': '0x0',
                'removed': False,
            }
        ]
    elif req['method'] == 'eth_getBlockByHash':
        resp['result'] = {
            "difficulty": "0x2",
            "extraData": "0xd883010919846765746888676f312e31352e35856c696e757800000000000000449bddee2636a0554442001fd4ef258d590ad7531d944a2ff5334ea53cfd254c3f5caa0cbeba09ec41bb963e6ea94f68c49d86ca4f20b6ee003634656d8dcce500",
            "gasLimit": "0x7a1200",
            "gasUsed": "0x6fbc6",
            "hash": "0xabc9aa063a7e94ae30daf47dc64e8bccea7a0a81ff6423797866a86b660e2fea",
            "logsBloom": "0x00000000000000000000000040000000000000000000000000000000000000000000200000000100000000000000000000000000000000000000000000000000000000001000000000000008000000000000000001000040000000001200000400000000000000000000000004000000000000000000000000000010000001000000000000020000000008000008000400000000000000000000001000000000000800000000000000000000010000000000000000000000000000000000000000000002012000000008000000000000000000000000000000000000000000000000000000000000000200000000000000000000001000000000008000000000",
            "miner": "0x0000000000000000000000000000000000000000",
            "mixHash": "0x0000000000000000000000000000000000000000000000000000000000000000",
            "nonce": "0x0000000000000000",
            "number": "0x32a64",
            "parentHash": "0xb1534e9f3394f6f7bf846a593724b9e4ca73c92fd75e92b60808b562909c3cd3",
            "receiptsRoot": "0x415869fc87ad81732266f527ea5ae79b44d7914620af3d82d32e8c2b693a4150",
            "sha3Uncles": "0x1dcc4de8dec75d7aab85b567b6ccd41ad312451b948a7413f0a142fd40d49347",
            "size": "0x334",
            "stateRoot": "0x5d73eb4759b9c57925148dc8599f31cfbda0f284b084525c1288b298390f5771",
            "timestamp": "0x5fc952b7",
            "totalDifficulty": "0x654c9",
            "transactions": ["0x812a5955e060b7d377ffa0a0046782810dd975abac9c0a94c6819854192ef119"],
            "transactionsRoot": "0xf7b548ef7f8f13bff5ed8a74c955b76dc33597a6dffe2ff062738e528fcf41a0",
            "uncles": [],
        }
    elif req['method'] == 'eth_getBalance':
        resp['result'] = str(1 * 10 ** 18)

    return web.json_response(resp)


def main(argv):
    app = web.Application()
    app['lighthouse'] = True
    app['prysm'] = not app['lighthouse']
    app.add_routes(routes)
    web.run_app(app, port=os.getenv('PORT', 8080))
    return app
