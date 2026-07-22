import datetime

from google.protobuf import duration_pb2 as _duration_pb2
from google.protobuf import timestamp_pb2 as _timestamp_pb2
import cedar_sky_pb2 as _cedar_sky_pb2
import cedar_common_pb2 as _cedar_common_pb2
from google.protobuf.internal import containers as _containers
from google.protobuf.internal import enum_type_wrapper as _enum_type_wrapper
from google.protobuf import descriptor as _descriptor
from google.protobuf import message as _message
from collections.abc import Iterable as _Iterable, Mapping as _Mapping
from typing import ClassVar as _ClassVar, Optional as _Optional, Union as _Union

DESCRIPTOR: _descriptor.FileDescriptor

class FeatureLevel(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
    __slots__ = ()
    FEATURE_LEVEL_UNSPECIFIED: _ClassVar[FeatureLevel]
    DIY: _ClassVar[FeatureLevel]
    BASIC: _ClassVar[FeatureLevel]
    PLUS: _ClassVar[FeatureLevel]

class ImuTrackerState(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
    __slots__ = ()
    TRACKER_STATE_UNKNOWN: _ClassVar[ImuTrackerState]
    MOTIONLESS: _ClassVar[ImuTrackerState]
    MOVING: _ClassVar[ImuTrackerState]
    LOST: _ClassVar[ImuTrackerState]

class OperatingMode(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
    __slots__ = ()
    MODE_UNSPECIFIED: _ClassVar[OperatingMode]
    SETUP: _ClassVar[OperatingMode]
    OPERATE: _ClassVar[OperatingMode]

class CelestialCoordFormat(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
    __slots__ = ()
    FORMAT_UNSPECIFIED: _ClassVar[CelestialCoordFormat]
    DECIMAL: _ClassVar[CelestialCoordFormat]
    HMS_DMS: _ClassVar[CelestialCoordFormat]

class MountType(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
    __slots__ = ()
    MOUNT_UNSPECIFIED: _ClassVar[MountType]
    EQUATORIAL: _ClassVar[MountType]
    ALT_AZ: _ClassVar[MountType]

class DisplayOrientation(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
    __slots__ = ()
    ORIENTATION_UNSPECIFIED: _ClassVar[DisplayOrientation]
    LANDSCAPE: _ClassVar[DisplayOrientation]
    PORTRAIT: _ClassVar[DisplayOrientation]

class CalibrationFailureReason(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
    __slots__ = ()
    REASON_UNSPECIFIED: _ClassVar[CalibrationFailureReason]
    TOO_FEW_STARS: _ClassVar[CalibrationFailureReason]
    BRIGHT_SKY: _ClassVar[CalibrationFailureReason]
    SOLVER_FAILED: _ClassVar[CalibrationFailureReason]
FEATURE_LEVEL_UNSPECIFIED: FeatureLevel
DIY: FeatureLevel
BASIC: FeatureLevel
PLUS: FeatureLevel
TRACKER_STATE_UNKNOWN: ImuTrackerState
MOTIONLESS: ImuTrackerState
MOVING: ImuTrackerState
LOST: ImuTrackerState
MODE_UNSPECIFIED: OperatingMode
SETUP: OperatingMode
OPERATE: OperatingMode
FORMAT_UNSPECIFIED: CelestialCoordFormat
DECIMAL: CelestialCoordFormat
HMS_DMS: CelestialCoordFormat
MOUNT_UNSPECIFIED: MountType
EQUATORIAL: MountType
ALT_AZ: MountType
ORIENTATION_UNSPECIFIED: DisplayOrientation
LANDSCAPE: DisplayOrientation
PORTRAIT: DisplayOrientation
REASON_UNSPECIFIED: CalibrationFailureReason
TOO_FEW_STARS: CalibrationFailureReason
BRIGHT_SKY: CalibrationFailureReason
SOLVER_FAILED: CalibrationFailureReason

class ServerInformation(_message.Message):
    __slots__ = ("product_name", "copyright", "cedar_server_version", "feature_level", "processor_model", "cpu_core_count", "os_version", "serial_number", "cpu_temperature", "server_time", "camera", "imu_model", "imu", "imu_angular_speed", "imu_tracker_state", "wifi_access_point", "connection_status", "demo_image_names", "system_load_average", "cedar_load_average")
    PRODUCT_NAME_FIELD_NUMBER: _ClassVar[int]
    COPYRIGHT_FIELD_NUMBER: _ClassVar[int]
    CEDAR_SERVER_VERSION_FIELD_NUMBER: _ClassVar[int]
    FEATURE_LEVEL_FIELD_NUMBER: _ClassVar[int]
    PROCESSOR_MODEL_FIELD_NUMBER: _ClassVar[int]
    CPU_CORE_COUNT_FIELD_NUMBER: _ClassVar[int]
    OS_VERSION_FIELD_NUMBER: _ClassVar[int]
    SERIAL_NUMBER_FIELD_NUMBER: _ClassVar[int]
    CPU_TEMPERATURE_FIELD_NUMBER: _ClassVar[int]
    SERVER_TIME_FIELD_NUMBER: _ClassVar[int]
    CAMERA_FIELD_NUMBER: _ClassVar[int]
    IMU_MODEL_FIELD_NUMBER: _ClassVar[int]
    IMU_FIELD_NUMBER: _ClassVar[int]
    IMU_ANGULAR_SPEED_FIELD_NUMBER: _ClassVar[int]
    IMU_TRACKER_STATE_FIELD_NUMBER: _ClassVar[int]
    WIFI_ACCESS_POINT_FIELD_NUMBER: _ClassVar[int]
    CONNECTION_STATUS_FIELD_NUMBER: _ClassVar[int]
    DEMO_IMAGE_NAMES_FIELD_NUMBER: _ClassVar[int]
    SYSTEM_LOAD_AVERAGE_FIELD_NUMBER: _ClassVar[int]
    CEDAR_LOAD_AVERAGE_FIELD_NUMBER: _ClassVar[int]
    product_name: str
    copyright: str
    cedar_server_version: str
    feature_level: FeatureLevel
    processor_model: str
    cpu_core_count: int
    os_version: str
    serial_number: str
    cpu_temperature: float
    server_time: _timestamp_pb2.Timestamp
    camera: CameraModel
    imu_model: str
    imu: ImuState
    imu_angular_speed: float
    imu_tracker_state: ImuTrackerState
    wifi_access_point: WiFiAccessPoint
    connection_status: ConnectionStatus
    demo_image_names: _containers.RepeatedScalarFieldContainer[str]
    system_load_average: float
    cedar_load_average: float
    def __init__(self, product_name: _Optional[str] = ..., copyright: _Optional[str] = ..., cedar_server_version: _Optional[str] = ..., feature_level: _Optional[_Union[FeatureLevel, str]] = ..., processor_model: _Optional[str] = ..., cpu_core_count: _Optional[int] = ..., os_version: _Optional[str] = ..., serial_number: _Optional[str] = ..., cpu_temperature: _Optional[float] = ..., server_time: _Optional[_Union[datetime.datetime, _timestamp_pb2.Timestamp, _Mapping]] = ..., camera: _Optional[_Union[CameraModel, _Mapping]] = ..., imu_model: _Optional[str] = ..., imu: _Optional[_Union[ImuState, _Mapping]] = ..., imu_angular_speed: _Optional[float] = ..., imu_tracker_state: _Optional[_Union[ImuTrackerState, str]] = ..., wifi_access_point: _Optional[_Union[WiFiAccessPoint, _Mapping]] = ..., connection_status: _Optional[_Union[ConnectionStatus, _Mapping]] = ..., demo_image_names: _Optional[_Iterable[str]] = ..., system_load_average: _Optional[float] = ..., cedar_load_average: _Optional[float] = ...) -> None: ...

class CameraModel(_message.Message):
    __slots__ = ("model", "model_detail", "image_width", "image_height")
    MODEL_FIELD_NUMBER: _ClassVar[int]
    MODEL_DETAIL_FIELD_NUMBER: _ClassVar[int]
    IMAGE_WIDTH_FIELD_NUMBER: _ClassVar[int]
    IMAGE_HEIGHT_FIELD_NUMBER: _ClassVar[int]
    model: str
    model_detail: str
    image_width: int
    image_height: int
    def __init__(self, model: _Optional[str] = ..., model_detail: _Optional[str] = ..., image_width: _Optional[int] = ..., image_height: _Optional[int] = ...) -> None: ...

class ImuState(_message.Message):
    __slots__ = ("accel_x", "accel_y", "accel_z", "angle_rate_x", "angle_rate_y", "angle_rate_z")
    ACCEL_X_FIELD_NUMBER: _ClassVar[int]
    ACCEL_Y_FIELD_NUMBER: _ClassVar[int]
    ACCEL_Z_FIELD_NUMBER: _ClassVar[int]
    ANGLE_RATE_X_FIELD_NUMBER: _ClassVar[int]
    ANGLE_RATE_Y_FIELD_NUMBER: _ClassVar[int]
    ANGLE_RATE_Z_FIELD_NUMBER: _ClassVar[int]
    accel_x: float
    accel_y: float
    accel_z: float
    angle_rate_x: float
    angle_rate_y: float
    angle_rate_z: float
    def __init__(self, accel_x: _Optional[float] = ..., accel_y: _Optional[float] = ..., accel_z: _Optional[float] = ..., angle_rate_x: _Optional[float] = ..., angle_rate_y: _Optional[float] = ..., angle_rate_z: _Optional[float] = ...) -> None: ...

class WiFiAccessPoint(_message.Message):
    __slots__ = ("ssid", "psk", "channel")
    SSID_FIELD_NUMBER: _ClassVar[int]
    PSK_FIELD_NUMBER: _ClassVar[int]
    CHANNEL_FIELD_NUMBER: _ClassVar[int]
    ssid: str
    psk: str
    channel: int
    def __init__(self, ssid: _Optional[str] = ..., psk: _Optional[str] = ..., channel: _Optional[int] = ...) -> None: ...

class ConnectionStatus(_message.Message):
    __slots__ = ("cedar_wifi", "cedar_bluetooth", "lx200_wifi", "lx200_bluetooth")
    CEDAR_WIFI_FIELD_NUMBER: _ClassVar[int]
    CEDAR_BLUETOOTH_FIELD_NUMBER: _ClassVar[int]
    LX200_WIFI_FIELD_NUMBER: _ClassVar[int]
    LX200_BLUETOOTH_FIELD_NUMBER: _ClassVar[int]
    cedar_wifi: int
    cedar_bluetooth: int
    lx200_wifi: int
    lx200_bluetooth: int
    def __init__(self, cedar_wifi: _Optional[int] = ..., cedar_bluetooth: _Optional[int] = ..., lx200_wifi: _Optional[int] = ..., lx200_bluetooth: _Optional[int] = ...) -> None: ...

class FixedSettings(_message.Message):
    __slots__ = ("observer_location", "current_time", "session_name", "max_exposure_time")
    OBSERVER_LOCATION_FIELD_NUMBER: _ClassVar[int]
    CURRENT_TIME_FIELD_NUMBER: _ClassVar[int]
    SESSION_NAME_FIELD_NUMBER: _ClassVar[int]
    MAX_EXPOSURE_TIME_FIELD_NUMBER: _ClassVar[int]
    observer_location: LatLong
    current_time: _timestamp_pb2.Timestamp
    session_name: str
    max_exposure_time: _duration_pb2.Duration
    def __init__(self, observer_location: _Optional[_Union[LatLong, _Mapping]] = ..., current_time: _Optional[_Union[datetime.datetime, _timestamp_pb2.Timestamp, _Mapping]] = ..., session_name: _Optional[str] = ..., max_exposure_time: _Optional[_Union[datetime.timedelta, _duration_pb2.Duration, _Mapping]] = ...) -> None: ...

class LatLong(_message.Message):
    __slots__ = ("latitude", "longitude")
    LATITUDE_FIELD_NUMBER: _ClassVar[int]
    LONGITUDE_FIELD_NUMBER: _ClassVar[int]
    latitude: float
    longitude: float
    def __init__(self, latitude: _Optional[float] = ..., longitude: _Optional[float] = ...) -> None: ...

class OperationSettings(_message.Message):
    __slots__ = ("operating_mode", "daylight_mode", "focus_assist_mode", "log_dwelled_positions", "catalog_entry_match", "demo_image_filename", "use_imu")
    OPERATING_MODE_FIELD_NUMBER: _ClassVar[int]
    DAYLIGHT_MODE_FIELD_NUMBER: _ClassVar[int]
    FOCUS_ASSIST_MODE_FIELD_NUMBER: _ClassVar[int]
    LOG_DWELLED_POSITIONS_FIELD_NUMBER: _ClassVar[int]
    CATALOG_ENTRY_MATCH_FIELD_NUMBER: _ClassVar[int]
    DEMO_IMAGE_FILENAME_FIELD_NUMBER: _ClassVar[int]
    USE_IMU_FIELD_NUMBER: _ClassVar[int]
    operating_mode: OperatingMode
    daylight_mode: bool
    focus_assist_mode: bool
    log_dwelled_positions: bool
    catalog_entry_match: _cedar_sky_pb2.CatalogEntryMatch
    demo_image_filename: str
    use_imu: bool
    def __init__(self, operating_mode: _Optional[_Union[OperatingMode, str]] = ..., daylight_mode: _Optional[bool] = ..., focus_assist_mode: _Optional[bool] = ..., log_dwelled_positions: _Optional[bool] = ..., catalog_entry_match: _Optional[_Union[_cedar_sky_pb2.CatalogEntryMatch, _Mapping]] = ..., demo_image_filename: _Optional[str] = ..., use_imu: _Optional[bool] = ...) -> None: ...

class Preferences(_message.Message):
    __slots__ = ("celestial_coord_format", "eyepiece_fov", "night_vision_theme", "hide_app_bar", "mount_type", "observer_location", "catalog_entry_match", "max_distance_active", "max_distance", "min_elevation_active", "min_elevation", "ordering", "advanced", "text_size_index", "boresight_pixel", "right_handed", "celestial_coord_choice", "perf_gauge_choice", "screen_always_on", "dont_show_items", "skip_focus", "skip_alignment")
    CELESTIAL_COORD_FORMAT_FIELD_NUMBER: _ClassVar[int]
    EYEPIECE_FOV_FIELD_NUMBER: _ClassVar[int]
    NIGHT_VISION_THEME_FIELD_NUMBER: _ClassVar[int]
    HIDE_APP_BAR_FIELD_NUMBER: _ClassVar[int]
    MOUNT_TYPE_FIELD_NUMBER: _ClassVar[int]
    OBSERVER_LOCATION_FIELD_NUMBER: _ClassVar[int]
    CATALOG_ENTRY_MATCH_FIELD_NUMBER: _ClassVar[int]
    MAX_DISTANCE_ACTIVE_FIELD_NUMBER: _ClassVar[int]
    MAX_DISTANCE_FIELD_NUMBER: _ClassVar[int]
    MIN_ELEVATION_ACTIVE_FIELD_NUMBER: _ClassVar[int]
    MIN_ELEVATION_FIELD_NUMBER: _ClassVar[int]
    ORDERING_FIELD_NUMBER: _ClassVar[int]
    ADVANCED_FIELD_NUMBER: _ClassVar[int]
    TEXT_SIZE_INDEX_FIELD_NUMBER: _ClassVar[int]
    BORESIGHT_PIXEL_FIELD_NUMBER: _ClassVar[int]
    RIGHT_HANDED_FIELD_NUMBER: _ClassVar[int]
    CELESTIAL_COORD_CHOICE_FIELD_NUMBER: _ClassVar[int]
    PERF_GAUGE_CHOICE_FIELD_NUMBER: _ClassVar[int]
    SCREEN_ALWAYS_ON_FIELD_NUMBER: _ClassVar[int]
    DONT_SHOW_ITEMS_FIELD_NUMBER: _ClassVar[int]
    SKIP_FOCUS_FIELD_NUMBER: _ClassVar[int]
    SKIP_ALIGNMENT_FIELD_NUMBER: _ClassVar[int]
    celestial_coord_format: CelestialCoordFormat
    eyepiece_fov: float
    night_vision_theme: bool
    hide_app_bar: bool
    mount_type: MountType
    observer_location: LatLong
    catalog_entry_match: _cedar_sky_pb2.CatalogEntryMatch
    max_distance_active: bool
    max_distance: float
    min_elevation_active: bool
    min_elevation: float
    ordering: _cedar_sky_pb2.Ordering
    advanced: bool
    text_size_index: int
    boresight_pixel: ImageCoord
    right_handed: bool
    celestial_coord_choice: str
    perf_gauge_choice: str
    screen_always_on: bool
    dont_show_items: _containers.RepeatedScalarFieldContainer[str]
    skip_focus: bool
    skip_alignment: bool
    def __init__(self, celestial_coord_format: _Optional[_Union[CelestialCoordFormat, str]] = ..., eyepiece_fov: _Optional[float] = ..., night_vision_theme: _Optional[bool] = ..., hide_app_bar: _Optional[bool] = ..., mount_type: _Optional[_Union[MountType, str]] = ..., observer_location: _Optional[_Union[LatLong, _Mapping]] = ..., catalog_entry_match: _Optional[_Union[_cedar_sky_pb2.CatalogEntryMatch, _Mapping]] = ..., max_distance_active: _Optional[bool] = ..., max_distance: _Optional[float] = ..., min_elevation_active: _Optional[bool] = ..., min_elevation: _Optional[float] = ..., ordering: _Optional[_Union[_cedar_sky_pb2.Ordering, str]] = ..., advanced: _Optional[bool] = ..., text_size_index: _Optional[int] = ..., boresight_pixel: _Optional[_Union[ImageCoord, _Mapping]] = ..., right_handed: _Optional[bool] = ..., celestial_coord_choice: _Optional[str] = ..., perf_gauge_choice: _Optional[str] = ..., screen_always_on: _Optional[bool] = ..., dont_show_items: _Optional[_Iterable[str]] = ..., skip_focus: _Optional[bool] = ..., skip_alignment: _Optional[bool] = ...) -> None: ...

class FrameRequest(_message.Message):
    __slots__ = ("prev_frame_id", "prev_solution_id", "non_blocking", "display_orientation")
    PREV_FRAME_ID_FIELD_NUMBER: _ClassVar[int]
    PREV_SOLUTION_ID_FIELD_NUMBER: _ClassVar[int]
    NON_BLOCKING_FIELD_NUMBER: _ClassVar[int]
    DISPLAY_ORIENTATION_FIELD_NUMBER: _ClassVar[int]
    prev_frame_id: int
    prev_solution_id: int
    non_blocking: bool
    display_orientation: DisplayOrientation
    def __init__(self, prev_frame_id: _Optional[int] = ..., prev_solution_id: _Optional[int] = ..., non_blocking: _Optional[bool] = ..., display_orientation: _Optional[_Union[DisplayOrientation, str]] = ...) -> None: ...

class FrameResult(_message.Message):
    __slots__ = ("has_result", "frame_id", "solution_id", "server_information", "fixed_settings", "preferences", "operation_settings", "calibration_data", "image", "exposure_time", "capture_time", "star_candidates", "hot_pixel_count", "star_count_moving_average", "plate_solution", "noise_estimate", "processing_stats", "boresight_position", "calibrating", "calibration_progress", "skip_focus_active", "center_peak_position", "center_peak_value", "center_peak_image", "daylight_focus_zoom_image", "location_based_info", "slew_request", "boresight_image", "polar_align_advice", "labeled_catalog_entries", "unlabeled_catalog_entries", "boresight_catalog_entry", "boresight_catalog_entry_distance", "boresight_constellation")
    HAS_RESULT_FIELD_NUMBER: _ClassVar[int]
    FRAME_ID_FIELD_NUMBER: _ClassVar[int]
    SOLUTION_ID_FIELD_NUMBER: _ClassVar[int]
    SERVER_INFORMATION_FIELD_NUMBER: _ClassVar[int]
    FIXED_SETTINGS_FIELD_NUMBER: _ClassVar[int]
    PREFERENCES_FIELD_NUMBER: _ClassVar[int]
    OPERATION_SETTINGS_FIELD_NUMBER: _ClassVar[int]
    CALIBRATION_DATA_FIELD_NUMBER: _ClassVar[int]
    IMAGE_FIELD_NUMBER: _ClassVar[int]
    EXPOSURE_TIME_FIELD_NUMBER: _ClassVar[int]
    CAPTURE_TIME_FIELD_NUMBER: _ClassVar[int]
    STAR_CANDIDATES_FIELD_NUMBER: _ClassVar[int]
    HOT_PIXEL_COUNT_FIELD_NUMBER: _ClassVar[int]
    STAR_COUNT_MOVING_AVERAGE_FIELD_NUMBER: _ClassVar[int]
    PLATE_SOLUTION_FIELD_NUMBER: _ClassVar[int]
    NOISE_ESTIMATE_FIELD_NUMBER: _ClassVar[int]
    PROCESSING_STATS_FIELD_NUMBER: _ClassVar[int]
    BORESIGHT_POSITION_FIELD_NUMBER: _ClassVar[int]
    CALIBRATING_FIELD_NUMBER: _ClassVar[int]
    CALIBRATION_PROGRESS_FIELD_NUMBER: _ClassVar[int]
    SKIP_FOCUS_ACTIVE_FIELD_NUMBER: _ClassVar[int]
    CENTER_PEAK_POSITION_FIELD_NUMBER: _ClassVar[int]
    CENTER_PEAK_VALUE_FIELD_NUMBER: _ClassVar[int]
    CENTER_PEAK_IMAGE_FIELD_NUMBER: _ClassVar[int]
    DAYLIGHT_FOCUS_ZOOM_IMAGE_FIELD_NUMBER: _ClassVar[int]
    LOCATION_BASED_INFO_FIELD_NUMBER: _ClassVar[int]
    SLEW_REQUEST_FIELD_NUMBER: _ClassVar[int]
    BORESIGHT_IMAGE_FIELD_NUMBER: _ClassVar[int]
    POLAR_ALIGN_ADVICE_FIELD_NUMBER: _ClassVar[int]
    LABELED_CATALOG_ENTRIES_FIELD_NUMBER: _ClassVar[int]
    UNLABELED_CATALOG_ENTRIES_FIELD_NUMBER: _ClassVar[int]
    BORESIGHT_CATALOG_ENTRY_FIELD_NUMBER: _ClassVar[int]
    BORESIGHT_CATALOG_ENTRY_DISTANCE_FIELD_NUMBER: _ClassVar[int]
    BORESIGHT_CONSTELLATION_FIELD_NUMBER: _ClassVar[int]
    has_result: bool
    frame_id: int
    solution_id: int
    server_information: ServerInformation
    fixed_settings: FixedSettings
    preferences: Preferences
    operation_settings: OperationSettings
    calibration_data: CalibrationData
    image: Image
    exposure_time: _duration_pb2.Duration
    capture_time: _timestamp_pb2.Timestamp
    star_candidates: _containers.RepeatedCompositeFieldContainer[StarCentroid]
    hot_pixel_count: int
    star_count_moving_average: float
    plate_solution: PlateSolution
    noise_estimate: float
    processing_stats: ProcessingStats
    boresight_position: ImageCoord
    calibrating: bool
    calibration_progress: float
    skip_focus_active: bool
    center_peak_position: ImageCoord
    center_peak_value: int
    center_peak_image: Image
    daylight_focus_zoom_image: Image
    location_based_info: LocationBasedInfo
    slew_request: SlewRequest
    boresight_image: Image
    polar_align_advice: PolarAlignAdvice
    labeled_catalog_entries: _containers.RepeatedCompositeFieldContainer[FovCatalogEntry]
    unlabeled_catalog_entries: _containers.RepeatedCompositeFieldContainer[FovCatalogEntry]
    boresight_catalog_entry: FovCatalogEntry
    boresight_catalog_entry_distance: float
    boresight_constellation: _cedar_sky_pb2.Constellation
    def __init__(self, has_result: _Optional[bool] = ..., frame_id: _Optional[int] = ..., solution_id: _Optional[int] = ..., server_information: _Optional[_Union[ServerInformation, _Mapping]] = ..., fixed_settings: _Optional[_Union[FixedSettings, _Mapping]] = ..., preferences: _Optional[_Union[Preferences, _Mapping]] = ..., operation_settings: _Optional[_Union[OperationSettings, _Mapping]] = ..., calibration_data: _Optional[_Union[CalibrationData, _Mapping]] = ..., image: _Optional[_Union[Image, _Mapping]] = ..., exposure_time: _Optional[_Union[datetime.timedelta, _duration_pb2.Duration, _Mapping]] = ..., capture_time: _Optional[_Union[datetime.datetime, _timestamp_pb2.Timestamp, _Mapping]] = ..., star_candidates: _Optional[_Iterable[_Union[StarCentroid, _Mapping]]] = ..., hot_pixel_count: _Optional[int] = ..., star_count_moving_average: _Optional[float] = ..., plate_solution: _Optional[_Union[PlateSolution, _Mapping]] = ..., noise_estimate: _Optional[float] = ..., processing_stats: _Optional[_Union[ProcessingStats, _Mapping]] = ..., boresight_position: _Optional[_Union[ImageCoord, _Mapping]] = ..., calibrating: _Optional[bool] = ..., calibration_progress: _Optional[float] = ..., skip_focus_active: _Optional[bool] = ..., center_peak_position: _Optional[_Union[ImageCoord, _Mapping]] = ..., center_peak_value: _Optional[int] = ..., center_peak_image: _Optional[_Union[Image, _Mapping]] = ..., daylight_focus_zoom_image: _Optional[_Union[Image, _Mapping]] = ..., location_based_info: _Optional[_Union[LocationBasedInfo, _Mapping]] = ..., slew_request: _Optional[_Union[SlewRequest, _Mapping]] = ..., boresight_image: _Optional[_Union[Image, _Mapping]] = ..., polar_align_advice: _Optional[_Union[PolarAlignAdvice, _Mapping]] = ..., labeled_catalog_entries: _Optional[_Iterable[_Union[FovCatalogEntry, _Mapping]]] = ..., unlabeled_catalog_entries: _Optional[_Iterable[_Union[FovCatalogEntry, _Mapping]]] = ..., boresight_catalog_entry: _Optional[_Union[FovCatalogEntry, _Mapping]] = ..., boresight_catalog_entry_distance: _Optional[float] = ..., boresight_constellation: _Optional[_Union[_cedar_sky_pb2.Constellation, _Mapping]] = ...) -> None: ...

class Image(_message.Message):
    __slots__ = ("binning_factor", "rectangle", "image_data", "rotation_size_ratio")
    BINNING_FACTOR_FIELD_NUMBER: _ClassVar[int]
    RECTANGLE_FIELD_NUMBER: _ClassVar[int]
    IMAGE_DATA_FIELD_NUMBER: _ClassVar[int]
    ROTATION_SIZE_RATIO_FIELD_NUMBER: _ClassVar[int]
    binning_factor: int
    rectangle: Rectangle
    image_data: bytes
    rotation_size_ratio: float
    def __init__(self, binning_factor: _Optional[int] = ..., rectangle: _Optional[_Union[Rectangle, _Mapping]] = ..., image_data: _Optional[bytes] = ..., rotation_size_ratio: _Optional[float] = ...) -> None: ...

class Rectangle(_message.Message):
    __slots__ = ("origin_x", "origin_y", "width", "height")
    ORIGIN_X_FIELD_NUMBER: _ClassVar[int]
    ORIGIN_Y_FIELD_NUMBER: _ClassVar[int]
    WIDTH_FIELD_NUMBER: _ClassVar[int]
    HEIGHT_FIELD_NUMBER: _ClassVar[int]
    origin_x: int
    origin_y: int
    width: int
    height: int
    def __init__(self, origin_x: _Optional[int] = ..., origin_y: _Optional[int] = ..., width: _Optional[int] = ..., height: _Optional[int] = ...) -> None: ...

class StarCentroid(_message.Message):
    __slots__ = ("centroid_position", "brightness", "num_saturated", "magnitude")
    CENTROID_POSITION_FIELD_NUMBER: _ClassVar[int]
    BRIGHTNESS_FIELD_NUMBER: _ClassVar[int]
    NUM_SATURATED_FIELD_NUMBER: _ClassVar[int]
    MAGNITUDE_FIELD_NUMBER: _ClassVar[int]
    centroid_position: ImageCoord
    brightness: float
    num_saturated: int
    magnitude: float
    def __init__(self, centroid_position: _Optional[_Union[ImageCoord, _Mapping]] = ..., brightness: _Optional[float] = ..., num_saturated: _Optional[int] = ..., magnitude: _Optional[float] = ...) -> None: ...

class ImageCoord(_message.Message):
    __slots__ = ("x", "y")
    X_FIELD_NUMBER: _ClassVar[int]
    Y_FIELD_NUMBER: _ClassVar[int]
    x: float
    y: float
    def __init__(self, x: _Optional[float] = ..., y: _Optional[float] = ...) -> None: ...

class PlateSolution(_message.Message):
    __slots__ = ("image_sky_coord", "roll", "fov", "distortion", "rmse", "p90_error", "max_error", "num_matches", "prob", "epoch_equinox", "epoch_proper_motion", "solve_time", "target_sky_coord", "target_pixel", "matched_stars", "pattern_centroids", "catalog_stars", "rotation_matrix", "solution_from_imu")
    IMAGE_SKY_COORD_FIELD_NUMBER: _ClassVar[int]
    ROLL_FIELD_NUMBER: _ClassVar[int]
    FOV_FIELD_NUMBER: _ClassVar[int]
    DISTORTION_FIELD_NUMBER: _ClassVar[int]
    RMSE_FIELD_NUMBER: _ClassVar[int]
    P90_ERROR_FIELD_NUMBER: _ClassVar[int]
    MAX_ERROR_FIELD_NUMBER: _ClassVar[int]
    NUM_MATCHES_FIELD_NUMBER: _ClassVar[int]
    PROB_FIELD_NUMBER: _ClassVar[int]
    EPOCH_EQUINOX_FIELD_NUMBER: _ClassVar[int]
    EPOCH_PROPER_MOTION_FIELD_NUMBER: _ClassVar[int]
    SOLVE_TIME_FIELD_NUMBER: _ClassVar[int]
    TARGET_SKY_COORD_FIELD_NUMBER: _ClassVar[int]
    TARGET_PIXEL_FIELD_NUMBER: _ClassVar[int]
    MATCHED_STARS_FIELD_NUMBER: _ClassVar[int]
    PATTERN_CENTROIDS_FIELD_NUMBER: _ClassVar[int]
    CATALOG_STARS_FIELD_NUMBER: _ClassVar[int]
    ROTATION_MATRIX_FIELD_NUMBER: _ClassVar[int]
    SOLUTION_FROM_IMU_FIELD_NUMBER: _ClassVar[int]
    image_sky_coord: _cedar_common_pb2.CelestialCoord
    roll: float
    fov: float
    distortion: float
    rmse: float
    p90_error: float
    max_error: float
    num_matches: int
    prob: float
    epoch_equinox: int
    epoch_proper_motion: float
    solve_time: _duration_pb2.Duration
    target_sky_coord: _containers.RepeatedCompositeFieldContainer[_cedar_common_pb2.CelestialCoord]
    target_pixel: _containers.RepeatedCompositeFieldContainer[ImageCoord]
    matched_stars: _containers.RepeatedCompositeFieldContainer[StarInfo]
    pattern_centroids: _containers.RepeatedCompositeFieldContainer[ImageCoord]
    catalog_stars: _containers.RepeatedCompositeFieldContainer[StarInfo]
    rotation_matrix: _containers.RepeatedScalarFieldContainer[float]
    solution_from_imu: bool
    def __init__(self, image_sky_coord: _Optional[_Union[_cedar_common_pb2.CelestialCoord, _Mapping]] = ..., roll: _Optional[float] = ..., fov: _Optional[float] = ..., distortion: _Optional[float] = ..., rmse: _Optional[float] = ..., p90_error: _Optional[float] = ..., max_error: _Optional[float] = ..., num_matches: _Optional[int] = ..., prob: _Optional[float] = ..., epoch_equinox: _Optional[int] = ..., epoch_proper_motion: _Optional[float] = ..., solve_time: _Optional[_Union[datetime.timedelta, _duration_pb2.Duration, _Mapping]] = ..., target_sky_coord: _Optional[_Iterable[_Union[_cedar_common_pb2.CelestialCoord, _Mapping]]] = ..., target_pixel: _Optional[_Iterable[_Union[ImageCoord, _Mapping]]] = ..., matched_stars: _Optional[_Iterable[_Union[StarInfo, _Mapping]]] = ..., pattern_centroids: _Optional[_Iterable[_Union[ImageCoord, _Mapping]]] = ..., catalog_stars: _Optional[_Iterable[_Union[StarInfo, _Mapping]]] = ..., rotation_matrix: _Optional[_Iterable[float]] = ..., solution_from_imu: _Optional[bool] = ...) -> None: ...

class StarInfo(_message.Message):
    __slots__ = ("pixel", "sky_coord", "mag")
    PIXEL_FIELD_NUMBER: _ClassVar[int]
    SKY_COORD_FIELD_NUMBER: _ClassVar[int]
    MAG_FIELD_NUMBER: _ClassVar[int]
    pixel: ImageCoord
    sky_coord: _cedar_common_pb2.CelestialCoord
    mag: float
    def __init__(self, pixel: _Optional[_Union[ImageCoord, _Mapping]] = ..., sky_coord: _Optional[_Union[_cedar_common_pb2.CelestialCoord, _Mapping]] = ..., mag: _Optional[float] = ...) -> None: ...

class ProcessingStats(_message.Message):
    __slots__ = ("acquire_latency", "detect_latency", "detect_other_latency", "solve_latency", "solve_other_latency", "solve_attempt_fraction", "solve_success_fraction", "serve_latency", "solve_interval")
    ACQUIRE_LATENCY_FIELD_NUMBER: _ClassVar[int]
    DETECT_LATENCY_FIELD_NUMBER: _ClassVar[int]
    DETECT_OTHER_LATENCY_FIELD_NUMBER: _ClassVar[int]
    SOLVE_LATENCY_FIELD_NUMBER: _ClassVar[int]
    SOLVE_OTHER_LATENCY_FIELD_NUMBER: _ClassVar[int]
    SOLVE_ATTEMPT_FRACTION_FIELD_NUMBER: _ClassVar[int]
    SOLVE_SUCCESS_FRACTION_FIELD_NUMBER: _ClassVar[int]
    SERVE_LATENCY_FIELD_NUMBER: _ClassVar[int]
    SOLVE_INTERVAL_FIELD_NUMBER: _ClassVar[int]
    acquire_latency: ValueStats
    detect_latency: ValueStats
    detect_other_latency: ValueStats
    solve_latency: ValueStats
    solve_other_latency: ValueStats
    solve_attempt_fraction: ValueStats
    solve_success_fraction: ValueStats
    serve_latency: ValueStats
    solve_interval: ValueStats
    def __init__(self, acquire_latency: _Optional[_Union[ValueStats, _Mapping]] = ..., detect_latency: _Optional[_Union[ValueStats, _Mapping]] = ..., detect_other_latency: _Optional[_Union[ValueStats, _Mapping]] = ..., solve_latency: _Optional[_Union[ValueStats, _Mapping]] = ..., solve_other_latency: _Optional[_Union[ValueStats, _Mapping]] = ..., solve_attempt_fraction: _Optional[_Union[ValueStats, _Mapping]] = ..., solve_success_fraction: _Optional[_Union[ValueStats, _Mapping]] = ..., serve_latency: _Optional[_Union[ValueStats, _Mapping]] = ..., solve_interval: _Optional[_Union[ValueStats, _Mapping]] = ...) -> None: ...

class ValueStats(_message.Message):
    __slots__ = ("recent", "session")
    RECENT_FIELD_NUMBER: _ClassVar[int]
    SESSION_FIELD_NUMBER: _ClassVar[int]
    recent: DescriptiveStats
    session: DescriptiveStats
    def __init__(self, recent: _Optional[_Union[DescriptiveStats, _Mapping]] = ..., session: _Optional[_Union[DescriptiveStats, _Mapping]] = ...) -> None: ...

class DescriptiveStats(_message.Message):
    __slots__ = ("min", "max", "mean", "stddev", "median", "median_absolute_deviation")
    MIN_FIELD_NUMBER: _ClassVar[int]
    MAX_FIELD_NUMBER: _ClassVar[int]
    MEAN_FIELD_NUMBER: _ClassVar[int]
    STDDEV_FIELD_NUMBER: _ClassVar[int]
    MEDIAN_FIELD_NUMBER: _ClassVar[int]
    MEDIAN_ABSOLUTE_DEVIATION_FIELD_NUMBER: _ClassVar[int]
    min: float
    max: float
    mean: float
    stddev: float
    median: float
    median_absolute_deviation: float
    def __init__(self, min: _Optional[float] = ..., max: _Optional[float] = ..., mean: _Optional[float] = ..., stddev: _Optional[float] = ..., median: _Optional[float] = ..., median_absolute_deviation: _Optional[float] = ...) -> None: ...

class CalibrationData(_message.Message):
    __slots__ = ("calibration_time", "calibration_failure_reason", "target_exposure_time", "camera_offset", "fov_horizontal", "fov_vertical", "lens_distortion", "match_max_error", "lens_fl_mm", "pixel_angular_size", "gyro_zero_bias_x", "gyro_zero_bias_y", "gyro_zero_bias_z", "gyro_transform_error_fraction", "camera_view_gyro_axis", "camera_view_misalignment", "camera_up_gyro_axis", "camera_up_misalignment", "bright_spot_map_count")
    CALIBRATION_TIME_FIELD_NUMBER: _ClassVar[int]
    CALIBRATION_FAILURE_REASON_FIELD_NUMBER: _ClassVar[int]
    TARGET_EXPOSURE_TIME_FIELD_NUMBER: _ClassVar[int]
    CAMERA_OFFSET_FIELD_NUMBER: _ClassVar[int]
    FOV_HORIZONTAL_FIELD_NUMBER: _ClassVar[int]
    FOV_VERTICAL_FIELD_NUMBER: _ClassVar[int]
    LENS_DISTORTION_FIELD_NUMBER: _ClassVar[int]
    MATCH_MAX_ERROR_FIELD_NUMBER: _ClassVar[int]
    LENS_FL_MM_FIELD_NUMBER: _ClassVar[int]
    PIXEL_ANGULAR_SIZE_FIELD_NUMBER: _ClassVar[int]
    GYRO_ZERO_BIAS_X_FIELD_NUMBER: _ClassVar[int]
    GYRO_ZERO_BIAS_Y_FIELD_NUMBER: _ClassVar[int]
    GYRO_ZERO_BIAS_Z_FIELD_NUMBER: _ClassVar[int]
    GYRO_TRANSFORM_ERROR_FRACTION_FIELD_NUMBER: _ClassVar[int]
    CAMERA_VIEW_GYRO_AXIS_FIELD_NUMBER: _ClassVar[int]
    CAMERA_VIEW_MISALIGNMENT_FIELD_NUMBER: _ClassVar[int]
    CAMERA_UP_GYRO_AXIS_FIELD_NUMBER: _ClassVar[int]
    CAMERA_UP_MISALIGNMENT_FIELD_NUMBER: _ClassVar[int]
    BRIGHT_SPOT_MAP_COUNT_FIELD_NUMBER: _ClassVar[int]
    calibration_time: _timestamp_pb2.Timestamp
    calibration_failure_reason: CalibrationFailureReason
    target_exposure_time: _duration_pb2.Duration
    camera_offset: int
    fov_horizontal: float
    fov_vertical: float
    lens_distortion: float
    match_max_error: float
    lens_fl_mm: float
    pixel_angular_size: float
    gyro_zero_bias_x: float
    gyro_zero_bias_y: float
    gyro_zero_bias_z: float
    gyro_transform_error_fraction: float
    camera_view_gyro_axis: str
    camera_view_misalignment: float
    camera_up_gyro_axis: str
    camera_up_misalignment: float
    bright_spot_map_count: int
    def __init__(self, calibration_time: _Optional[_Union[datetime.datetime, _timestamp_pb2.Timestamp, _Mapping]] = ..., calibration_failure_reason: _Optional[_Union[CalibrationFailureReason, str]] = ..., target_exposure_time: _Optional[_Union[datetime.timedelta, _duration_pb2.Duration, _Mapping]] = ..., camera_offset: _Optional[int] = ..., fov_horizontal: _Optional[float] = ..., fov_vertical: _Optional[float] = ..., lens_distortion: _Optional[float] = ..., match_max_error: _Optional[float] = ..., lens_fl_mm: _Optional[float] = ..., pixel_angular_size: _Optional[float] = ..., gyro_zero_bias_x: _Optional[float] = ..., gyro_zero_bias_y: _Optional[float] = ..., gyro_zero_bias_z: _Optional[float] = ..., gyro_transform_error_fraction: _Optional[float] = ..., camera_view_gyro_axis: _Optional[str] = ..., camera_view_misalignment: _Optional[float] = ..., camera_up_gyro_axis: _Optional[str] = ..., camera_up_misalignment: _Optional[float] = ..., bright_spot_map_count: _Optional[int] = ...) -> None: ...

class LocationBasedInfo(_message.Message):
    __slots__ = ("zenith_roll_angle", "altitude", "azimuth", "hour_angle")
    ZENITH_ROLL_ANGLE_FIELD_NUMBER: _ClassVar[int]
    ALTITUDE_FIELD_NUMBER: _ClassVar[int]
    AZIMUTH_FIELD_NUMBER: _ClassVar[int]
    HOUR_ANGLE_FIELD_NUMBER: _ClassVar[int]
    zenith_roll_angle: float
    altitude: float
    azimuth: float
    hour_angle: float
    def __init__(self, zenith_roll_angle: _Optional[float] = ..., altitude: _Optional[float] = ..., azimuth: _Optional[float] = ..., hour_angle: _Optional[float] = ...) -> None: ...

class SlewRequest(_message.Message):
    __slots__ = ("target", "target_catalog_entry", "target_distance", "target_angle", "offset_rotation_axis", "offset_tilt_axis", "image_pos")
    TARGET_FIELD_NUMBER: _ClassVar[int]
    TARGET_CATALOG_ENTRY_FIELD_NUMBER: _ClassVar[int]
    TARGET_DISTANCE_FIELD_NUMBER: _ClassVar[int]
    TARGET_ANGLE_FIELD_NUMBER: _ClassVar[int]
    OFFSET_ROTATION_AXIS_FIELD_NUMBER: _ClassVar[int]
    OFFSET_TILT_AXIS_FIELD_NUMBER: _ClassVar[int]
    IMAGE_POS_FIELD_NUMBER: _ClassVar[int]
    target: _cedar_common_pb2.CelestialCoord
    target_catalog_entry: _cedar_sky_pb2.CatalogEntry
    target_distance: float
    target_angle: float
    offset_rotation_axis: float
    offset_tilt_axis: float
    image_pos: ImageCoord
    def __init__(self, target: _Optional[_Union[_cedar_common_pb2.CelestialCoord, _Mapping]] = ..., target_catalog_entry: _Optional[_Union[_cedar_sky_pb2.CatalogEntry, _Mapping]] = ..., target_distance: _Optional[float] = ..., target_angle: _Optional[float] = ..., offset_rotation_axis: _Optional[float] = ..., offset_tilt_axis: _Optional[float] = ..., image_pos: _Optional[_Union[ImageCoord, _Mapping]] = ...) -> None: ...

class PolarAlignAdvice(_message.Message):
    __slots__ = ("azimuth_correction", "altitude_correction")
    AZIMUTH_CORRECTION_FIELD_NUMBER: _ClassVar[int]
    ALTITUDE_CORRECTION_FIELD_NUMBER: _ClassVar[int]
    azimuth_correction: ErrorBoundedValue
    altitude_correction: ErrorBoundedValue
    def __init__(self, azimuth_correction: _Optional[_Union[ErrorBoundedValue, _Mapping]] = ..., altitude_correction: _Optional[_Union[ErrorBoundedValue, _Mapping]] = ...) -> None: ...

class ErrorBoundedValue(_message.Message):
    __slots__ = ("value", "error")
    VALUE_FIELD_NUMBER: _ClassVar[int]
    ERROR_FIELD_NUMBER: _ClassVar[int]
    value: float
    error: float
    def __init__(self, value: _Optional[float] = ..., error: _Optional[float] = ...) -> None: ...

class FovCatalogEntry(_message.Message):
    __slots__ = ("entry", "image_pos", "altitude", "azimuth")
    ENTRY_FIELD_NUMBER: _ClassVar[int]
    IMAGE_POS_FIELD_NUMBER: _ClassVar[int]
    ALTITUDE_FIELD_NUMBER: _ClassVar[int]
    AZIMUTH_FIELD_NUMBER: _ClassVar[int]
    entry: _cedar_sky_pb2.CatalogEntry
    image_pos: ImageCoord
    altitude: float
    azimuth: float
    def __init__(self, entry: _Optional[_Union[_cedar_sky_pb2.CatalogEntry, _Mapping]] = ..., image_pos: _Optional[_Union[ImageCoord, _Mapping]] = ..., altitude: _Optional[float] = ..., azimuth: _Optional[float] = ...) -> None: ...

class ActionRequest(_message.Message):
    __slots__ = ("cancel_calibration", "capture_boresight", "designate_boresight", "shutdown_server", "restart_server", "initiate_slew", "stop_slew", "save_image", "update_wifi_access_point", "clear_dont_show_items", "designate_daylight_focus_region", "calibrate_dark_frame", "reset_hot_pixel_map", "crash_server", "wifi_enabled")
    CANCEL_CALIBRATION_FIELD_NUMBER: _ClassVar[int]
    CAPTURE_BORESIGHT_FIELD_NUMBER: _ClassVar[int]
    DESIGNATE_BORESIGHT_FIELD_NUMBER: _ClassVar[int]
    SHUTDOWN_SERVER_FIELD_NUMBER: _ClassVar[int]
    RESTART_SERVER_FIELD_NUMBER: _ClassVar[int]
    INITIATE_SLEW_FIELD_NUMBER: _ClassVar[int]
    STOP_SLEW_FIELD_NUMBER: _ClassVar[int]
    SAVE_IMAGE_FIELD_NUMBER: _ClassVar[int]
    UPDATE_WIFI_ACCESS_POINT_FIELD_NUMBER: _ClassVar[int]
    CLEAR_DONT_SHOW_ITEMS_FIELD_NUMBER: _ClassVar[int]
    DESIGNATE_DAYLIGHT_FOCUS_REGION_FIELD_NUMBER: _ClassVar[int]
    CALIBRATE_DARK_FRAME_FIELD_NUMBER: _ClassVar[int]
    RESET_HOT_PIXEL_MAP_FIELD_NUMBER: _ClassVar[int]
    CRASH_SERVER_FIELD_NUMBER: _ClassVar[int]
    WIFI_ENABLED_FIELD_NUMBER: _ClassVar[int]
    cancel_calibration: bool
    capture_boresight: bool
    designate_boresight: ImageCoord
    shutdown_server: bool
    restart_server: bool
    initiate_slew: _cedar_common_pb2.CelestialCoord
    stop_slew: bool
    save_image: bool
    update_wifi_access_point: WiFiAccessPoint
    clear_dont_show_items: bool
    designate_daylight_focus_region: ImageCoord
    calibrate_dark_frame: bool
    reset_hot_pixel_map: bool
    crash_server: bool
    wifi_enabled: bool
    def __init__(self, cancel_calibration: _Optional[bool] = ..., capture_boresight: _Optional[bool] = ..., designate_boresight: _Optional[_Union[ImageCoord, _Mapping]] = ..., shutdown_server: _Optional[bool] = ..., restart_server: _Optional[bool] = ..., initiate_slew: _Optional[_Union[_cedar_common_pb2.CelestialCoord, _Mapping]] = ..., stop_slew: _Optional[bool] = ..., save_image: _Optional[bool] = ..., update_wifi_access_point: _Optional[_Union[WiFiAccessPoint, _Mapping]] = ..., clear_dont_show_items: _Optional[bool] = ..., designate_daylight_focus_region: _Optional[_Union[ImageCoord, _Mapping]] = ..., calibrate_dark_frame: _Optional[bool] = ..., reset_hot_pixel_map: _Optional[bool] = ..., crash_server: _Optional[bool] = ..., wifi_enabled: _Optional[bool] = ...) -> None: ...

class ServerLogRequest(_message.Message):
    __slots__ = ("log_request",)
    LOG_REQUEST_FIELD_NUMBER: _ClassVar[int]
    log_request: int
    def __init__(self, log_request: _Optional[int] = ...) -> None: ...

class ServerLogResult(_message.Message):
    __slots__ = ("log_content",)
    LOG_CONTENT_FIELD_NUMBER: _ClassVar[int]
    log_content: str
    def __init__(self, log_content: _Optional[str] = ...) -> None: ...

class EmptyMessage(_message.Message):
    __slots__ = ()
    def __init__(self) -> None: ...

class GetBluetoothNameResponse(_message.Message):
    __slots__ = ("name", "address")
    NAME_FIELD_NUMBER: _ClassVar[int]
    ADDRESS_FIELD_NUMBER: _ClassVar[int]
    name: str
    address: str
    def __init__(self, name: _Optional[str] = ..., address: _Optional[str] = ...) -> None: ...

class BondedDevice(_message.Message):
    __slots__ = ("name", "address")
    NAME_FIELD_NUMBER: _ClassVar[int]
    ADDRESS_FIELD_NUMBER: _ClassVar[int]
    name: str
    address: str
    def __init__(self, name: _Optional[str] = ..., address: _Optional[str] = ...) -> None: ...

class GetBondedDevicesResponse(_message.Message):
    __slots__ = ("devices",)
    DEVICES_FIELD_NUMBER: _ClassVar[int]
    devices: _containers.RepeatedCompositeFieldContainer[BondedDevice]
    def __init__(self, devices: _Optional[_Iterable[_Union[BondedDevice, _Mapping]]] = ...) -> None: ...

class RemoveBondRequest(_message.Message):
    __slots__ = ("address",)
    ADDRESS_FIELD_NUMBER: _ClassVar[int]
    address: str
    def __init__(self, address: _Optional[str] = ...) -> None: ...

class SetPairingModeRequest(_message.Message):
    __slots__ = ("enabled", "forever")
    ENABLED_FIELD_NUMBER: _ClassVar[int]
    FOREVER_FIELD_NUMBER: _ClassVar[int]
    enabled: bool
    forever: bool
    def __init__(self, enabled: _Optional[bool] = ..., forever: _Optional[bool] = ...) -> None: ...
