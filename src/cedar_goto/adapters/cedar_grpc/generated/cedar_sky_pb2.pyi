import cedar_common_pb2 as _cedar_common_pb2
from google.protobuf.internal import containers as _containers
from google.protobuf.internal import enum_type_wrapper as _enum_type_wrapper
from google.protobuf import descriptor as _descriptor
from google.protobuf import message as _message
from collections.abc import Iterable as _Iterable, Mapping as _Mapping
from typing import ClassVar as _ClassVar, Optional as _Optional, Union as _Union

DESCRIPTOR: _descriptor.FileDescriptor

class Ordering(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
    __slots__ = ()
    UNSPECIFIED: _ClassVar[Ordering]
    BRIGHTNESS: _ClassVar[Ordering]
    SKY_LOCATION: _ClassVar[Ordering]
    ELEVATION: _ClassVar[Ordering]
UNSPECIFIED: Ordering
BRIGHTNESS: Ordering
SKY_LOCATION: Ordering
ELEVATION: Ordering

class QueryCatalogRequest(_message.Message):
    __slots__ = ("catalog_entry_match", "max_distance", "min_elevation", "decrowd_distance", "ordering", "limit_result", "text_search")
    CATALOG_ENTRY_MATCH_FIELD_NUMBER: _ClassVar[int]
    MAX_DISTANCE_FIELD_NUMBER: _ClassVar[int]
    MIN_ELEVATION_FIELD_NUMBER: _ClassVar[int]
    DECROWD_DISTANCE_FIELD_NUMBER: _ClassVar[int]
    ORDERING_FIELD_NUMBER: _ClassVar[int]
    LIMIT_RESULT_FIELD_NUMBER: _ClassVar[int]
    TEXT_SEARCH_FIELD_NUMBER: _ClassVar[int]
    catalog_entry_match: CatalogEntryMatch
    max_distance: float
    min_elevation: float
    decrowd_distance: float
    ordering: Ordering
    limit_result: int
    text_search: str
    def __init__(self, catalog_entry_match: _Optional[_Union[CatalogEntryMatch, _Mapping]] = ..., max_distance: _Optional[float] = ..., min_elevation: _Optional[float] = ..., decrowd_distance: _Optional[float] = ..., ordering: _Optional[_Union[Ordering, str]] = ..., limit_result: _Optional[int] = ..., text_search: _Optional[str] = ...) -> None: ...

class CatalogEntryMatch(_message.Message):
    __slots__ = ("faintest_magnitude", "match_catalog_label", "catalog_label", "match_object_type_label", "object_type_label")
    FAINTEST_MAGNITUDE_FIELD_NUMBER: _ClassVar[int]
    MATCH_CATALOG_LABEL_FIELD_NUMBER: _ClassVar[int]
    CATALOG_LABEL_FIELD_NUMBER: _ClassVar[int]
    MATCH_OBJECT_TYPE_LABEL_FIELD_NUMBER: _ClassVar[int]
    OBJECT_TYPE_LABEL_FIELD_NUMBER: _ClassVar[int]
    faintest_magnitude: int
    match_catalog_label: bool
    catalog_label: _containers.RepeatedScalarFieldContainer[str]
    match_object_type_label: bool
    object_type_label: _containers.RepeatedScalarFieldContainer[str]
    def __init__(self, faintest_magnitude: _Optional[int] = ..., match_catalog_label: _Optional[bool] = ..., catalog_label: _Optional[_Iterable[str]] = ..., match_object_type_label: _Optional[bool] = ..., object_type_label: _Optional[_Iterable[str]] = ...) -> None: ...

class QueryCatalogResponse(_message.Message):
    __slots__ = ("entries", "truncated_count")
    ENTRIES_FIELD_NUMBER: _ClassVar[int]
    TRUNCATED_COUNT_FIELD_NUMBER: _ClassVar[int]
    entries: _containers.RepeatedCompositeFieldContainer[SelectedCatalogEntry]
    truncated_count: int
    def __init__(self, entries: _Optional[_Iterable[_Union[SelectedCatalogEntry, _Mapping]]] = ..., truncated_count: _Optional[int] = ...) -> None: ...

class SelectedCatalogEntry(_message.Message):
    __slots__ = ("entry", "deduped_entries", "decrowded_entries", "altitude", "azimuth")
    ENTRY_FIELD_NUMBER: _ClassVar[int]
    DEDUPED_ENTRIES_FIELD_NUMBER: _ClassVar[int]
    DECROWDED_ENTRIES_FIELD_NUMBER: _ClassVar[int]
    ALTITUDE_FIELD_NUMBER: _ClassVar[int]
    AZIMUTH_FIELD_NUMBER: _ClassVar[int]
    entry: CatalogEntry
    deduped_entries: _containers.RepeatedCompositeFieldContainer[CatalogEntry]
    decrowded_entries: _containers.RepeatedCompositeFieldContainer[CatalogEntry]
    altitude: float
    azimuth: float
    def __init__(self, entry: _Optional[_Union[CatalogEntry, _Mapping]] = ..., deduped_entries: _Optional[_Iterable[_Union[CatalogEntry, _Mapping]]] = ..., decrowded_entries: _Optional[_Iterable[_Union[CatalogEntry, _Mapping]]] = ..., altitude: _Optional[float] = ..., azimuth: _Optional[float] = ...) -> None: ...

class CatalogEntry(_message.Message):
    __slots__ = ("catalog_label", "catalog_entry", "coord", "constellation", "object_type", "magnitude", "angular_size", "common_name", "notes")
    CATALOG_LABEL_FIELD_NUMBER: _ClassVar[int]
    CATALOG_ENTRY_FIELD_NUMBER: _ClassVar[int]
    COORD_FIELD_NUMBER: _ClassVar[int]
    CONSTELLATION_FIELD_NUMBER: _ClassVar[int]
    OBJECT_TYPE_FIELD_NUMBER: _ClassVar[int]
    MAGNITUDE_FIELD_NUMBER: _ClassVar[int]
    ANGULAR_SIZE_FIELD_NUMBER: _ClassVar[int]
    COMMON_NAME_FIELD_NUMBER: _ClassVar[int]
    NOTES_FIELD_NUMBER: _ClassVar[int]
    catalog_label: str
    catalog_entry: str
    coord: _cedar_common_pb2.CelestialCoord
    constellation: Constellation
    object_type: ObjectType
    magnitude: float
    angular_size: str
    common_name: str
    notes: str
    def __init__(self, catalog_label: _Optional[str] = ..., catalog_entry: _Optional[str] = ..., coord: _Optional[_Union[_cedar_common_pb2.CelestialCoord, _Mapping]] = ..., constellation: _Optional[_Union[Constellation, _Mapping]] = ..., object_type: _Optional[_Union[ObjectType, _Mapping]] = ..., magnitude: _Optional[float] = ..., angular_size: _Optional[str] = ..., common_name: _Optional[str] = ..., notes: _Optional[str] = ...) -> None: ...

class CatalogDescription(_message.Message):
    __slots__ = ("label", "name", "description", "source", "copyright", "license")
    LABEL_FIELD_NUMBER: _ClassVar[int]
    NAME_FIELD_NUMBER: _ClassVar[int]
    DESCRIPTION_FIELD_NUMBER: _ClassVar[int]
    SOURCE_FIELD_NUMBER: _ClassVar[int]
    COPYRIGHT_FIELD_NUMBER: _ClassVar[int]
    LICENSE_FIELD_NUMBER: _ClassVar[int]
    label: str
    name: str
    description: str
    source: str
    copyright: str
    license: str
    def __init__(self, label: _Optional[str] = ..., name: _Optional[str] = ..., description: _Optional[str] = ..., source: _Optional[str] = ..., copyright: _Optional[str] = ..., license: _Optional[str] = ...) -> None: ...

class CatalogDescriptionResponse(_message.Message):
    __slots__ = ("catalog_descriptions",)
    CATALOG_DESCRIPTIONS_FIELD_NUMBER: _ClassVar[int]
    catalog_descriptions: _containers.RepeatedCompositeFieldContainer[CatalogDescription]
    def __init__(self, catalog_descriptions: _Optional[_Iterable[_Union[CatalogDescription, _Mapping]]] = ...) -> None: ...

class ObjectType(_message.Message):
    __slots__ = ("label", "broad_category")
    LABEL_FIELD_NUMBER: _ClassVar[int]
    BROAD_CATEGORY_FIELD_NUMBER: _ClassVar[int]
    label: str
    broad_category: str
    def __init__(self, label: _Optional[str] = ..., broad_category: _Optional[str] = ...) -> None: ...

class ObjectTypeResponse(_message.Message):
    __slots__ = ("object_types",)
    OBJECT_TYPES_FIELD_NUMBER: _ClassVar[int]
    object_types: _containers.RepeatedCompositeFieldContainer[ObjectType]
    def __init__(self, object_types: _Optional[_Iterable[_Union[ObjectType, _Mapping]]] = ...) -> None: ...

class Constellation(_message.Message):
    __slots__ = ("label", "name")
    LABEL_FIELD_NUMBER: _ClassVar[int]
    NAME_FIELD_NUMBER: _ClassVar[int]
    label: str
    name: str
    def __init__(self, label: _Optional[str] = ..., name: _Optional[str] = ...) -> None: ...

class ConstellationResponse(_message.Message):
    __slots__ = ("constellations",)
    CONSTELLATIONS_FIELD_NUMBER: _ClassVar[int]
    constellations: _containers.RepeatedCompositeFieldContainer[Constellation]
    def __init__(self, constellations: _Optional[_Iterable[_Union[Constellation, _Mapping]]] = ...) -> None: ...

class CatalogEntryKey(_message.Message):
    __slots__ = ("cat_label", "entry")
    CAT_LABEL_FIELD_NUMBER: _ClassVar[int]
    ENTRY_FIELD_NUMBER: _ClassVar[int]
    cat_label: str
    entry: str
    def __init__(self, cat_label: _Optional[str] = ..., entry: _Optional[str] = ...) -> None: ...
