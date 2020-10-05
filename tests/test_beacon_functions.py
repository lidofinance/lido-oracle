import pytest
import requests
import json
from beacon import get_beacon, get_actual_slots, get_balances

key_list = [
    b"\xa3\x84\xf0\xd7w\x1d\xe0'\x8e\x0e\x9b\x13$\xb1\xa0\x9b\xb8\xb3\xf8\xa6-\xff\xcd\xb87\x06\xe38vM\xe8\x93\xc6H\xd6\xab\xdbN\x02^\xf0\xe8ZQ\x1aw\xa2.",
    b'\x91\x84Z\x12\xe0\x7fW\xbd\x1c\xa8\xba\x87\xc2\x97F\x1c u\xc7l\xe6\x00\xb9\xbb\x88\x99\xde\x00\x88\xf0\x92y\xee^R+\x84u\x9f\x1a\x85|J\x9a\x04\x8a5\x8b',
    b'\x81\xcc\xb4\xd16\xcc&\x13\xad*\xce7#\xac\xd5\xaaD\xf6\xb2r\xe2\x10\xe0\x08tN\xfb\xb2Oh\xe4\xbfaB\x7f\x07\xdb\x99\xdd\xc6\x87F\x10\xd7\xe5\x13\x08h',
    b'\xb8\xcd\x03\xfap-\xddG\xb8&\xa3P\x86Q\xe8@f_\x18h\xb3\x8cEp\x93\xcb\xcbi\x05\xf5\xa80P\xe3\x1b\x84p*\x9f\x19\x10\xc6\xff\xdf\x90\xad\xeb\x16']


class MockResponse:
    def __init__(self, version, json):
        self.text = version
        self.json_text = json

    def json(self):
        return json.loads(self.json_text)


@pytest.fixture
def lighthouse_requests(monkeypatch):
    version = "Lighthouse/v0.2.9-c6abc561+/x86_64-linux"
    head = '{"slot":417003,"block_root":"0x583c48d745dfd0545a4f299e66ae2e5777902f4b7abf3501e5b8ae35611d66bc","state_root":"0xc4e99adf863dc3b685135515973614a2c3ac6c3c9674c617e9adc0d313a47e2a","finalized_slot":416928,"finalized_block_root":"0x067ccf3ca686dadef54ed571bc38605f3516b83aa959f966ba8758124bc72d4a","justified_slot":416960,"justified_block_root":"0xa55856ef3cc97cce10a721a2ab84e1d1d47f4fca04252065851ccd25219ff2e7","previous_justified_slot":416928,"previous_justified_block_root":"0x067ccf3ca686dadef54ed571bc38605f3516b83aa959f966ba8758124bc72d4a"}'
    validators = '[{"pubkey":"0xa384f0d7771de0278e0e9b1324b1a09bb8b3f8a62dffcdb83706e338764de893c648d6abdb4e025ef0e85a511a77a22e","validator_index":18275,"balance":638349847291,"validator":{"pubkey":"0xa384f0d7771de0278e0e9b1324b1a09bb8b3f8a62dffcdb83706e338764de893c648d6abdb4e025ef0e85a511a77a22e","withdrawal_credentials":"0x00ea6e10ae09d000fe5c95024603c7c67918fbc08f6628cfabd6b2c9b46a1320","effective_balance":32000000000,"slashed":false,"activation_eligibility_epoch":0,"activation_epoch":0,"exit_epoch":18446744073709551615,"withdrawable_epoch":18446744073709551615}},{"pubkey":"0x91845a12e07f57bd1ca8ba87c297461c2075c76ce600b9bb8899de0088f09279ee5e522b84759f1a857c4a9a048a358b","validator_index":25550,"balance":190257076402,"validator":{"pubkey":"0x91845a12e07f57bd1ca8ba87c297461c2075c76ce600b9bb8899de0088f09279ee5e522b84759f1a857c4a9a048a358b","withdrawal_credentials":"0x004c3f7eb125a38b79f8c7090f1639cdde33c6183190aa7e41f50f19a271be85","effective_balance":32000000000,"slashed":false,"activation_eligibility_epoch":311,"activation_epoch":1404,"exit_epoch":18446744073709551615,"withdrawable_epoch":18446744073709551615}},{"pubkey":"0x81ccb4d136cc2613ad2ace3723acd5aa44f6b272e210e008744efbb24f68e4bf61427f07db99ddc6874610d7e5130868","validator_index":34231,"balance":160324259065,"validator":{"pubkey":"0x81ccb4d136cc2613ad2ace3723acd5aa44f6b272e210e008744efbb24f68e4bf61427f07db99ddc6874610d7e5130868","withdrawal_credentials":"0x0005df936de03f65e436f54507b42694ea591f3a6dec5b2d40e5a76268215b25","effective_balance":32000000000,"slashed":false,"activation_eligibility_epoch":3312,"activation_epoch":3768,"exit_epoch":18446744073709551615,"withdrawable_epoch":18446744073709551615}},{"pubkey":"0xb8cd03fa702ddd47b826a3508651e840665f1868b38c457093cbcb6905f5a83050e31b84702a9f1910c6ffdf90adeb16","validator_index":52757,"balance":159832673271,"validator":{"pubkey":"0xb8cd03fa702ddd47b826a3508651e840665f1868b38c457093cbcb6905f5a83050e31b84702a9f1910c6ffdf90adeb16","withdrawal_credentials":"0x00b8febd229fd6d1b0c8df13ea8094bb90054c7445890b3c70903ce51740897f","effective_balance":32000000000,"slashed":false,"activation_eligibility_epoch":4984,"activation_epoch":8399,"exit_epoch":18446744073709551615,"withdrawable_epoch":18446744073709551615}}]'
    state_root = '"0xed3f8e6219ba85abe4f5160e56446057d54f003e6fabf7895a028a97dd3e0aa1"'
    def mocked_get(uri, *args, **kwargs):
        """A method replacing Requests.get
        Returns a mocked response object (with json method)
        """

        if 'beacon/head' in uri:
            return MockResponse(version, head)
        elif 'beacon/validators' in uri:
            return MockResponse(version, validators)
        elif 'beacon/state_root' in uri:
            return MockResponse(version, state_root)
        else:
            return MockResponse(version, '')

    # finally, patch requests.get and requests.post with patched version
    monkeypatch.setattr(requests, 'get', mocked_get)
    monkeypatch.setattr(requests, 'post', mocked_get)


@pytest.fixture
def prysm_requests(monkeypatch):
    version = '{"version":"Prysm/v1.0.0-alpha.26/1a4129f5a6c6d30fd6710e763a85073f87d884d0. Built at: 2020-09-22 06:45:22+00:00","metadata":""}'
    head = '{"headSlot":"417334","headEpoch":"13041","headBlockRoot":"ZaI8Up4FwZ4NJsu92hut5gRh1e4icPeW+A9/VhwewiQ=","finalizedSlot":"417216","finalizedEpoch":"13038","finalizedBlockRoot":"+I9VxzTHZVyhztqdOxB/KzOZ5r61KdS0QKwZhXwfvKw=","justifiedSlot":"417280","justifiedEpoch":"13040","justifiedBlockRoot":"Q2Z4besi0NE9BtP20Z2tZYY3PiVJWZP+LKPlx+kbbGs=","previousJustifiedSlot":"417216","previousJustifiedEpoch":"13038","previousJustifiedBlockRoot":"+I9VxzTHZVyhztqdOxB/KzOZ5r61KdS0QKwZhXwfvKw="}'
    validators = '{"epoch":"13043","balances":[{"publicKey":"o4Tw13cd4CeODpsTJLGgm7iz+KYt/824NwbjOHZN6JPGSNar204CXvDoWlEad6Iu","index":"18275","balance":"638349971821"},{"publicKey":"kYRaEuB/V70cqLqHwpdGHCB1x2zmALm7iJneAIjwknnuXlIrhHWfGoV8SpoEijWL","index":"25550","balance":"190256940748"},{"publicKey":"gcy00TbMJhOtKs43I6zVqkT2snLiEOAIdE77sk9o5L9hQn8H25ndxodGENflEwho","index":"34231","balance":"160324387781"},{"publicKey":"uM0D+nAt3Ue4JqNQhlHoQGZfGGizjEVwk8vLaQX1qDBQ4xuEcCqfGRDG/9+QresW","index":"52757","balance":"159832537617"}],"nextPageToken":"","totalSize":4}'

    def mocked_get(uri, *args, **kwargs):
        """A method replacing Requests.get
        Returns a mocked response object (with json method)
        """

        if 'eth/v1alpha1/beacon/chainhead' in uri:
            return MockResponse(version, head)
        elif 'eth/v1alpha1/validators/balances' in uri:
            return MockResponse(version, validators)
        else:
            return MockResponse(version, '')

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
        return MockResponse(version, '')

    # finally, patch requests.get and requests.post with patched version
    monkeypatch.setattr(requests, 'get', mocked_get)
    monkeypatch.setattr(requests, 'post', mocked_get)


def test_version_lighthouse(lighthouse_requests):
    result = get_beacon('localhost')
    assert result == "Lighthouse"


def test_head_lighthouse(lighthouse_requests):
    result = get_actual_slots('Lighthouse', 'localhost')
    assert result['actual_slot'] == 417003 and result['finalized_slot'] == 416928


def test_balance_lighthouse(lighthouse_requests):
    result = get_balances('Lighthouse', 'localhost', 10, key_list)
    assert result == 1148763856029000000000


def test_version_prysm(prysm_requests):
    result = get_beacon('localhost')
    assert result == "Prysm"


def test_head_prysm(prysm_requests):
    result = get_actual_slots('Prysm', 'localhost')
    assert int(result['actual_slot']) == 417334 and int(result['finalized_slot']) == 417216


def test_balance_prysm(prysm_requests):
    result = get_balances('Prysm', 'localhost', 10, key_list)
    assert result == 1148763837967000000000


def test_version_bad(bad_requests):
    result = get_beacon('localhost')
    assert result == "None"


def test_balance_bad(bad_requests):
    with pytest.raises(ValueError) as event:
        get_balances('None', 'localhost', 10, key_list)
    assert event.type == ValueError
