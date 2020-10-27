import pytest
import requests
import json
from app.beacon import get_beacon

key_list = [
    b"\xa3\x84\xf0\xd7w\x1d\xe0'\x8e\x0e\x9b\x13$\xb1\xa0\x9b\xb8\xb3\xf8\xa6-\xff\xcd\xb87\x06\xe38vM\xe8\x93\xc6H\xd6\xab\xdbN\x02^\xf0\xe8ZQ\x1aw\xa2.",
    b'\x91\x84Z\x12\xe0\x7fW\xbd\x1c\xa8\xba\x87\xc2\x97F\x1c u\xc7l\xe6\x00\xb9\xbb\x88\x99\xde\x00\x88\xf0\x92y\xee^R+\x84u\x9f\x1a\x85|J\x9a\x04\x8a5\x8b',
    b'\x81\xcc\xb4\xd16\xcc&\x13\xad*\xce7#\xac\xd5\xaaD\xf6\xb2r\xe2\x10\xe0\x08tN\xfb\xb2Oh\xe4\xbfaB\x7f\x07\xdb\x99\xdd\xc6\x87F\x10\xd7\xe5\x13\x08h',
    b'\xb8\xcd\x03\xfap-\xddG\xb8&\xa3P\x86Q\xe8@f_\x18h\xb3\x8cEp\x93\xcb\xcbi\x05\xf5\xa80P\xe3\x1b\x84p*\x9f\x19\x10\xc6\xff\xdf\x90\xad\xeb\x16']


class MockResponse:
    def __init__(self, json):
        self.json_text = json
        self.text = json

    def json(self):
        return json.loads(self.json_text)


@pytest.fixture
def lighthouse_requests(monkeypatch):
    version = '{"data":{"version":"Lighthouse/v0.3.0-b185d7bb+/x86_64-linux"}}'
    genesis = '{"data":{"genesis_time":"1596546008","genesis_validators_root":"0x04700007fabc8282644aed6d1c7c9e21d38a03a0c4ba193f3afe428824b3a673","genesis_fork_version":"0x00000001"}}'
    head_actual = '{"data":{"root":"0xe363cadf644e5614384022f797cf95f6b372e758e64d19448b3018e38ccf1275","canonical":true,"header":{"message":{"slot":604932,"proposer_index":"73692","parent_root":"0xc8ef1ed2d3ec86f63214e393f5c636b2c186581d0cfbd24a795a9144c096b18d","state_root":"0x219e675555da8bb028e397a2bbd002e2beb6ce87992c2c4fbbc4f2ea77a2dcc1","body_root":"0x1228f4acdc347660a27567ede7a1c5cacc8483e4b345459cb65522ed21cbfb3b"},"signature":"0x8d8e2aea501704f65ed68d9824fa90d904e95b38c3e6a0495586e56c7f2943ad5a60bf5d6c4caf99008cc2a711869cc917b621a6c7044940d7b7e1d5418b1635bccf45595af61eef523ca3c53a897b6e459904ddf0bfde77d2287f33d1ea6383"}}}'
    head_finalized = '{"data":{"root":"0xb3806428b52a802fb9c4355b6e93a6afde02ecbd27a9f4723eb427c27cadb440","canonical":true,"header":{"message":{"slot":499647,"proposer_index":"5661","parent_root":"0x20b72159f84b8230337ddbc9c5c7390c62f25ae2bbe1573233cfa1985d46bc28","state_root":"0xeee95cb960b4ae4af746f4f28ddb99f88bd96553bb61b58b14ed5bf05357b423","body_root":"0x799b7113f58f9981bc6b908c74ec1df39cbda8c6deeaa4b245ad8f75304a9fcd"},"signature":"0xb46ac87d21eb57277e7f7e80f339ca13822c5db57f3b4b1d2fa3bd333b08b89e53abe48b754e41585aad8706e6241f03066c3a47bcf68a9da258d23e910c9cda73a5ea051ae37f15b0a42fd8c5e4afc154ebd2b8c18e732f1d62453339ffda82"}}}'
    validators = '{"data": [{"index": "18275", "balance": "31986354237", "status": "Active", "validator": {"pubkey": "0xa384f0d7771de0278e0e9b1324b1a09bb8b3f8a62dffcdb83706e338764de893c648d6abdb4e025ef0e85a511a77a22e", "withdrawal_credentials": "0x00ea6e10ae09d000fe5c95024603c7c67918fbc08f6628cfabd6b2c9b46a1320", "effective_balance": 32000000000, "slashed": false, "activation_eligibility_epoch": 0, "activation_epoch": 0, "exit_epoch": 18446744073709551615, "withdrawable_epoch": 18446744073709551615}}]}'
    state_root = '"0xed3f8e6219ba85abe4f5160e56446057d54f003e6fabf7895a028a97dd3e0aa1"'

    def mocked_get(uri, *args, **kwargs):
        """A method replacing Requests.get
        Returns a mocked response object (with json method)
        """
        if 'eth/v1/node/version' in uri:
            return MockResponse(version)
        if 'eth/v1/beacon/genesis' in uri:
            return MockResponse(genesis)
        if 'eth/v1/beacon/headers/head' in uri:
            return MockResponse(head_actual)
        if 'eth/v1/beacon/headers/finalized' in uri:
            return MockResponse(head_finalized)
        if uri.endswith('validators'):
            return MockResponse(validators)
        else:
            return MockResponse('')

    # finally, patch requests.get and requests.post with patched version
    monkeypatch.setattr(requests, 'get', mocked_get)
    monkeypatch.setattr(requests, 'post', mocked_get)


@pytest.fixture
def prysm_requests(monkeypatch):
    version = '{"version":"Prysm/v1.0.0-beta.0.rc/e6d688f6d5b407359b14e3da56e1bc4989c71b63. Built at: 2020-10-26 09:18:13+00:00","metadata":""}'
    genesis = '{"genesisTime":"2020-08-04T13:00:08Z","depositContractAddress":"B7OfT95KOLrOIStUbayHxY3+P9w=","genesisValidatorsRoot":"BHAAB/q8goJkSu1tHHyeIdOKA6DEuhk/Ov5CiCSzpnM="}'
    head = '{"headSlot":"604444","headEpoch":"18888","headBlockRoot":"9r3sKXLW15IvDspHYFkax+KT2/dfJRa0+w/6WcnpnsY=","finalizedSlot":"499648","finalizedEpoch":"15614","finalizedBlockRoot":"s4BkKLUqgC+5xDVbbpOmr94C7L0nqfRyPrQnwnyttEA=","justifiedSlot":"502560","justifiedEpoch":"15705","justifiedBlockRoot":"Zrpx37KbraJ8P5npgj2sQnL/GgV4FNBnI1M1hXHLAUI=","previousJustifiedSlot":"502560","previousJustifiedEpoch":"15705","previousJustifiedBlockRoot":"Zrpx37KbraJ8P5npgj2sQnL/GgV4FNBnI1M1hXHLAUI="}'
    validators = '{"epoch":"13043","balances":[{"publicKey":"o4Tw13cd4CeODpsTJLGgm7iz+KYt/824NwbjOHZN6JPGSNar204CXvDoWlEad6Iu","index":"18275","balance":"638349971821"},{"publicKey":"kYRaEuB/V70cqLqHwpdGHCB1x2zmALm7iJneAIjwknnuXlIrhHWfGoV8SpoEijWL","index":"25550","balance":"190256940748"},{"publicKey":"gcy00TbMJhOtKs43I6zVqkT2snLiEOAIdE77sk9o5L9hQn8H25ndxodGENflEwho","index":"34231","balance":"160324387781"},{"publicKey":"uM0D+nAt3Ue4JqNQhlHoQGZfGGizjEVwk8vLaQX1qDBQ4xuEcCqfGRDG/9+QresW","index":"52757","balance":"159832537617"}],"nextPageToken":"","totalSize":4}'

    def mocked_get(uri, *args, **kwargs):
        """A method replacing Requests.get
        Returns a mocked response object (with json method)
        """
        print(uri)
        if 'eth/v1alpha1/node/version' in uri:
            return MockResponse(version)
        if 'eth/v1alpha1/node/genesis' in uri:
            return MockResponse(genesis)
        if 'eth/v1alpha1/beacon/chainhead' in uri:
            return MockResponse(head)
        if 'eth/v1alpha1/validators/balances' in uri:
            return MockResponse(validators)
        else:
            return MockResponse('')

    # finally, patch requests.get and requests.post with patched version
    monkeypatch.setattr(requests, 'get', mocked_get)
    monkeypatch.setattr(requests, 'post', mocked_get)


@pytest.fixture
def bad_requests(monkeypatch):
    version = 'Mock'

    def mocked_get(uri, *args, **kwargs):
        """A method replacing Requests.get
        Returns a mocked response object (with json method)
        """
        return MockResponse(version)

    # finally, patch requests.get and requests.post with patched version
    monkeypatch.setattr(requests, 'get', mocked_get)
    monkeypatch.setattr(requests, 'post', mocked_get)


def test_version_lighthouse(lighthouse_requests):
    beacon = get_beacon('localhost', 1)
    assert "Lighthouse" in str(beacon.version)


def test_genesis_lighthouse(lighthouse_requests):
    beacon = get_beacon('localhost', 1)
    result = beacon.get_genesis()
    assert result == 1596546008


def test_head_lighthouse(lighthouse_requests):
    beacon = get_beacon('localhost', 1)
    result = beacon.get_actual_slot()
    assert result['actual_slot'] == 604932 and result['finalized_slot'] == 499647


def test_balance_lighthouse(lighthouse_requests):
    beacon = get_beacon('localhost', 1)
    result = beacon.get_balances(10, key_list)
    assert result == 31986354237000000000


def test_version_prysm(prysm_requests):
    beacon = get_beacon('localhost', 1)
    assert "Prysm" in str(beacon.version)


def test_genesis_prysm(prysm_requests):
    beacon = get_beacon('localhost', 1)
    result = beacon.get_genesis()
    assert result == 1596535208


def test_head_prysm(prysm_requests):
    beacon = get_beacon('localhost', 1)
    result = beacon.get_actual_slot()
    assert int(result['actual_slot']) == 604444 and int(result['finalized_slot']) == 499648


def test_balance_prysm(prysm_requests):
    beacon = get_beacon('localhost', 1)
    result = beacon.get_balances(10, key_list)
    assert result == 1148763837967000000000


def test_version_bad(bad_requests):
    with pytest.raises(ValueError) as event:
        get_beacon('localhost', 1)
    assert event.type == ValueError
