from typing import Any

from pydantic import BaseModel
from pydantic_factories import ModelFactory


class Web3Factory(ModelFactory[Any]):
    """Tweak the ModelFactory to add our web3 types."""
    __auto_register__ = True
    __model__ = BaseModel

    @classmethod
    def get_mock_value(cls, field_type: Any) -> Any:
        """Add our custom mock value."""
        if str(field_type) == "my_super_rare_datetime_field":
            return cls.get_faker().date_time_between()

        return super().get_mock_value(field_type)
