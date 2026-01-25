from pydantic import BaseModel, ConfigDict
from pydantic.alias_generators import to_snake

class HydroBaseModel(BaseModel):
    model_config = ConfigDict(
        alias_generator=to_snake,
        populate_by_name=True,
        from_attributes=True
    )
