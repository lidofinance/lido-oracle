import pytest
from count_referrals import DepositCalculator

DEPOSITS = [
    ["0xbb11472603c5104918745755fba69c485739d1c56",   0.1000000, "0xb38b395537d61aa15ae943a2b0fb26cba205ea260"],
    ["0xb73ba95e3af0ac6842d5614fef3f6b19b8c713b1c",   0.1000000, None],
    ["0xbc4c739151ba13ba51c0a8ba0ba54aa98a075451e",   1.0000001, "0xb9394ff3dd23a2472a26dec107ee6090c85163bda"],
    ["0xbccdf41e8eaea3d8b692dced0f78809349073a369",   2.0000002, "0xb5ea1337ec2cd55265cc302066646878f2157f485"],
    ["0xb3e2d23a01087c32cc9a37af9c1ee283f4b73b88b",   3.0000003, "0xb9ef07b250736742454d6f265b64f4064890439c6"],
    ["0xbb66e337cb55563d996871fceea0919baab8acd3e",   4.0000004, None],
    ["0xbd7bb2bea2df518db73f52acd18ebe989989b95bd",   5.0000005, "0xbbdc432b80372ab01e42cbd808a19f7aabc0f0c7f"],
    ["0xbcd74335181810f3a6bf245d7538f4f66bc4726a6",   6.0000006, "0xb0b718f8a7efacc9e1830cd55e43b301df31a8700"],
    ["0xb22ffbf04c4e26e05e51ba6718219348f0814eb19",  12.0000012, "0xb5ea1337ec2cd55265cc302066646878f2157f485"],
    ["0xb22ffbf04c4e26e05e51ba6718219348f0814eb19",  13.0000013, "0xb72acf9db0922e3d5947f796967066d3ecdbb2073"],
    ["0xbd391155be7e5b2d7c0d2d1af5b8efaae9f26dece", 130.0000030, "0xb38b395537d61aa15ae943a2b0fb26cba205ea260"],
]


@pytest.fixture
def filled_depo_calc():
    dc = DepositCalculator()
    for i in DEPOSITS:
        dep = dc.Deposit(addr=i[0], amount=i[1], referral=i[2])
        dc.session.add(dep)
    return dc


def test_get_depo_amounts_grouped_by_referral(filled_depo_calc):
    result = filled_depo_calc.get_depo_amounts_grouped_by_referral()
    print(result)
    assert len(result) == 7


def test_get_total_referral_deposits_sum(filled_depo_calc):
    result = filled_depo_calc.get_total_referral_deposits_sum()
    assert result == 172.1000072
