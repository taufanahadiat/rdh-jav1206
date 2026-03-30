from dataclasses import dataclass
from typing import List, Optional


@dataclass
class FieldDef:
    name: str
    type_name: str
    is_array: bool = False
    array_start: int = 0
    array_end: int = 0
    nested_fields: Optional[List["FieldDef"]] = None
