from google.protobuf import descriptor as _descriptor
from google.protobuf import message as _message
from typing import ClassVar as _ClassVar, Optional as _Optional

DESCRIPTOR: _descriptor.FileDescriptor

class CelestialCoord(_message.Message):
    __slots__ = ("ra", "dec", "epoch")
    RA_FIELD_NUMBER: _ClassVar[int]
    DEC_FIELD_NUMBER: _ClassVar[int]
    EPOCH_FIELD_NUMBER: _ClassVar[int]
    ra: float
    dec: float
    epoch: float
    def __init__(self, ra: _Optional[float] = ..., dec: _Optional[float] = ..., epoch: _Optional[float] = ...) -> None: ...
