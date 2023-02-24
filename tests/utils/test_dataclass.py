from dataclasses import dataclass, is_dataclass

import pytest

from src.utils.dataclass import list_of_dataclasses, Nested


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


@pytest.mark.unit
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
            }
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


def test_dataclasses_utils_fail_on_unexpected_key():
    with pytest.raises(TypeError):
        Car(
            wheel_count=2,
            wheels=[{'size': 1}],
            wheels_immutable=({'size': 1},),
            state={'cost': None},
        )
