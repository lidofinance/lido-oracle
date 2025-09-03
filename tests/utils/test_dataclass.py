from dataclasses import dataclass, is_dataclass
from typing import Any, Iterable

import pytest

from src.utils.dataclass import DecodeToDataclassException, FromResponse, Nested, list_of_dataclasses

pytestmark = pytest.mark.unit


@dataclass
class Wheel:
    size: str


@dataclass
class State:
    condition: str


@dataclass
class Car(Nested):
    wheel_count: int
    wheels: list[Wheel]
    wheels_immutable: tuple[Wheel]
    state: State


def test_dataclasses_utils():
    @list_of_dataclasses(Car)
    def get_cars() -> list[Car]:
        return [
            {
                'wheel_count': 4,
                'wheels': [{'size': 2}, {'size': 4}],
                'wheels_immutable': ({'size': 2}, {'size': 4}),
                'state': {'condition': 'good'},
            },
            {
                'wheel_count': 2,
                'wheels': [{'size': 1}],
                'wheels_immutable': ({'size': 1},),
                'state': {'condition': 'bad'},
            },
            {
                'wheel_count': 4,
                'wheels': [Wheel(size=2), Wheel(size=4)],
                'wheels_immutable': (Wheel(size=2), Wheel(size=4)),
                'state': State(condition='good'),
            },
        ]

    all_cars = get_cars()

    for car in all_cars:
        assert is_dataclass(car)
        assert is_dataclass(car.state)
        assert isinstance(car.wheels, list)
        assert isinstance(car.wheels_immutable, tuple)

        for wheel in car.wheels:
            assert is_dataclass(wheel)

        for wheel in car.wheels_immutable:
            assert is_dataclass(wheel)


def test_list_of_dataclasses_with_wrong_type():
    @list_of_dataclasses(Car)
    def get_cars_with_already_as_cars() -> list[Car]:
        return [
            Car(
                **{
                    'wheel_count': 4,
                    'wheels': [{'size': 2}, {'size': 4}],
                    'wheels_immutable': ({'size': 2}, {'size': 4}),
                    'state': {'condition': 'good'},
                }
            )
        ]

    with pytest.raises(DecodeToDataclassException):
        get_cars_with_already_as_cars()


def test_list_of_dataclasses_empty():
    @list_of_dataclasses(Car)
    def get_no_cars() -> list[Car]:
        return []

    assert get_no_cars() == []


def test_list_of_dataclasses_generator():
    @list_of_dataclasses(Car)
    def get_iterable_cars() -> Iterable:
        return range(10)

    with pytest.raises(DecodeToDataclassException):
        get_iterable_cars()


def test_list_of_dataclasses_with_mixed_types():
    @list_of_dataclasses(Car)
    def get_cars_inconsistent() -> list[Any]:
        return [
            {
                'wheel_count': 2,
                'wheels': [{'size': 1}],
                'wheels_immutable': ({'size': 1},),
                'state': {'condition': 'bad'},
            },
            Car(
                **{
                    'wheel_count': 4,
                    'wheels': [{'size': 2}, {'size': 4}],
                    'wheels_immutable': ({'size': 2}, {'size': 4}),
                    'state': {'condition': 'good'},
                }
            ),
        ]

    with pytest.raises(TypeError):
        get_cars_inconsistent()


def test_dataclasses_utils_fail_on_unexpected_key():
    with pytest.raises(TypeError):
        Car(
            wheel_count=2,
            wheels=[{'size': 1}],
            wheels_immutable=({'size': 1},),
            state={'cost': None},
        )


@dataclass
class Pet(FromResponse):
    name: str
    age: int


def test_dataclass_ignore_extra_fields():
    response = {"name": "Bob", "age": 5}
    pet = Pet.from_response(**response)
    assert pet == Pet(name="Bob", age=5)

    response_with_extra_fields = {"name": "Bob", "age": 5, "extra": "field"}
    pet = Pet.from_response(**response_with_extra_fields)
    assert pet == Pet(name="Bob", age=5)


def test_dataclass_raises_missing_field():
    response = {"name": "Bob"}
    with pytest.raises(TypeError, match="age"):
        Pet.from_response(**response)


@dataclass
class Hooman(Nested, FromResponse):
    favourite_pet: Pet
    pets: list[Pet]


def test_dataclass_nested_with_extra_fields():
    hooman_response = dict(
        favourite_pet={"name": "Bob", "age": 5, "extra": "field"}, pets=[{"name": "Bob", "age": 5, "extra": "field"}]
    )
    hooman = Hooman.from_response(**hooman_response)
    assert hooman == Hooman(favourite_pet=Pet(name="Bob", age=5), pets=[Pet(name="Bob", age=5)])


def test_dataclass_nested_raises_missing_field():
    response = dict(pets=[{"name": "Bob", "age": 5, "extra": "field"}])
    with pytest.raises(TypeError, match="favourite_pet"):
        Hooman.from_response(**response)


@dataclass
class ObjectWithNumericFields(FromResponse, Nested):
    sequence: list[int]
    digit: int
    name: str


def test_dataclass_nested_converts_numberish():
    response = {"sequence": ["1", "1", "2", "3", "5"], "digit": "4", "name": "Name"}
    obj = ObjectWithNumericFields.from_response(**response)
    assert obj.sequence == [1, 1, 2, 3, 5]
    assert obj.digit == 4
