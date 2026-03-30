from dataclasses import dataclass, field


@dataclass
class Node:
    kind: str
    name: str = ""
    data_type: str = ""
    comment: str = ""
    init: str = ""
    array_start: int = 0
    array_end: int = 0
    children: list["Node"] = field(default_factory=list)


@dataclass
class Cursor:
    byte: int = 0
    bit: int = 0

    def clone(self) -> "Cursor":
        return Cursor(self.byte, self.bit)


@dataclass
class Row:
    dbsym: int
    address: str
    name: str
    data_type: str
    initvalue: str
    comment: str
