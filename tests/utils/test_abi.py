from collections import namedtuple
from dataclasses import dataclass

import pytest

from src.utils.abi import camel_to_snake, named_tuple_to_dataclass

pytestmark = pytest.mark.unit


@dataclass
class CarDataclass:
    car_name: str
    car_size: int
    super_car: bool


CarTuple = namedtuple('Car', ['carName', 'carSize'])


def test_named_tuple_to_dataclass():
    Car = namedtuple('Car', ['carName', 'carSize', 'super_car'])
    car = Car('mazda', 1, True)

    supercar = named_tuple_to_dataclass(car, CarDataclass)
    assert supercar.car_name == car[0]
    assert supercar.car_size == car[1]
    assert supercar.super_car == car[2]


def test_camel_to_snake():
    assert camel_to_snake('CamelCase') == 'camel_case'
    assert camel_to_snake('getHTTPResponseCode') == 'get_http_response_code'
    assert camel_to_snake('HTTPResponseCodeXYZ') == 'http_response_code_xyz'
