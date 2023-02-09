from dataclasses import dataclass, is_dataclass

import pytest

from src.utils.dataclass import list_of_dataclasses, nested_dataclass


@dataclass
class Wheel:
    size: str


@dataclass
class State:
    condition: str


@nested_dataclass
class Car:
    wheel_count: int
    wheels: list[Wheel]
    state: State


@pytest.mark.unit
def test_dataclasses_utils():
    cars = [{'wheel_count': 4, }]

    @list_of_dataclasses(Car)
    def get_cars() -> list[Car]:
        return [
            {
                'wheel_count': 4,
                'wheels': [{'size': 2}, {'size': 4}],
                'state': {'condition': 'good'},
            },
            {
                'wheel_count': 2,
                'wheels': [{'size': 1}],
                'state': {'condition': 'bad'},
            }
        ]

    all_cars = get_cars()

    for car in all_cars:
        assert is_dataclass(car)
        assert is_dataclass(car.state)

        for wheel in car.wheels:
            assert is_dataclass(wheel)

    with pytest.raises(TypeError):
        Car(
            wheel_count=2,
            wheels=[{'size': 1}],
            state={'cost': None},
        )
