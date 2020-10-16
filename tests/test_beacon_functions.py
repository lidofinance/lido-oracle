import pytest
import requests
import json
from app.beacon import get_beacon, get_actual_slots, get_balances, get_slot_or_epoch

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
    head = '{"data":{"root":"0x6c4ba8e9a00d4d1cfd7eba6ba2ecef3df9115f6c8f81198121bf595cb71692d4","canonical":true,"header":{"message":{"slot":371584,"proposer_index":"6206","parent_root":"0xf763b14fea0ec00b532a82f5799fcf199fae857615c286013ba148a220146e32","state_root":"0x641b0cbe9f4c2f11c30dec3db91d2cecd1ccdb71cc51206d87c80c465c025caa","body_root":"0xaa271df080531bf695831b2660abef717763bb9047d5ae3685d0eba44e2d8169"},"signature":"0xafd2fae4e5352d8c61897553e87451570d69ca6e7151be1bc96bf10daa3fc034221f22af974ca20b5f16789a44be5f6e057bfb8b74994257881041040e2420b6c65dce691a5772a4d9e3d028b1726903032d02f223518324cb20460a62a15c07"}}}'
    validators = '{"data":[{"index":"0","balance":"32013376556","status":"Active","validator":{"pubkey":"0x81ccb4d136cc2613ad2ace3723acd5aa44f6b272e210e008744efbb24f68e4bf61427f07db99ddc6874610d7e5130868","withdrawal_credentials":"0x0010361af430aa7ab4a9567eaaca50ec5e02315ca1513d9ee8d73bde96370091","effective_balance":32000000000,"slashed":false,"activation_eligibility_epoch":0,"activation_epoch":0,"exit_epoch":18446744073709551615,"withdrawable_epoch":18446744073709551615}}]}'
    state_root = '"0xed3f8e6219ba85abe4f5160e56446057d54f003e6fabf7895a028a97dd3e0aa1"'

    def mocked_get(uri, *args, **kwargs):
        """A method replacing Requests.get
        Returns a mocked response object (with json method)
        """
        print(uri)
        if 'eth/v1/beacon/headers/' in uri:
            return MockResponse(version, head)
        elif uri.endswith('validators'):
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
    assert result['actual_slot'] == 371584 and result['finalized_slot'] == 371584


def test_balance_lighthouse(lighthouse_requests):
    result = get_balances('Lighthouse', 'localhost', 10, key_list)
    assert result == 32013376556000000000


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


def test_slot_or_epoch_lighthouse():
    result = get_slot_or_epoch('Lighthouse', 13041, 32)
    assert result == 417312


def test_slot_or_epoch_prysm():
    result = get_slot_or_epoch('Prysm', 13041, 32)
    assert result == 13041


def test_slot_or_epoch_bad():
    with pytest.raises(ValueError) as event:
        get_slot_or_epoch('localhost', 13041, 32)
    assert event.type == ValueError
