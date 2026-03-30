from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional


@dataclass
class PlcSource:
    db_num: int
    name: str
    script_path: Path
    kind: str
    awl_path: Optional[Path] = None
    source_file: Optional[str] = None
    total_bytes: int = 0
    type_map: Dict[str, Any] = field(default_factory=dict)
    db_fields: List[Any] = field(default_factory=list)
    size_cache: Dict[str, int] = field(default_factory=dict)
    disabled_reason: str = ""
