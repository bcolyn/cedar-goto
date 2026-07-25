"""ASCOM Alpaca error numbers and the standard JSON response envelope.

See the Alpaca API spec: every response carries ClientTransactionID,
ServerTransactionID, ErrorNumber (0 = success) and ErrorMessage, with the
actual return value (if any) in Value.
"""
from __future__ import annotations

import itertools

# ASCOM error codes (subset actually raised by this server).
NOT_IMPLEMENTED = 0x400  # 1024
INVALID_VALUE = 0x401  # 1025
VALUE_NOT_SET = 0x402  # 1026
NOT_CONNECTED = 0x407  # 1031
PARKED = 0x408  # 1032
INVALID_OPERATION = 0x40B  # 1035
ACTION_NOT_IMPLEMENTED = 0x40C  # 1036
DRIVER_ERROR_BASE = 0x500  # 1280


class AlpacaError(Exception):
    def __init__(self, error_number: int, message: str) -> None:
        super().__init__(message)
        self.error_number = error_number
        self.message = message


class NotConnectedError(AlpacaError):
    def __init__(self, message: str = "Device not connected") -> None:
        super().__init__(NOT_CONNECTED, message)


class ParkedError(AlpacaError):
    def __init__(self, message: str = "Telescope is parked") -> None:
        super().__init__(PARKED, message)


class ActionNotImplementedError(AlpacaError):
    def __init__(self, action: str) -> None:
        super().__init__(ACTION_NOT_IMPLEMENTED, f"Action not implemented: {action}")


class InvalidValueError(AlpacaError):
    def __init__(self, message: str) -> None:
        super().__init__(INVALID_VALUE, message)


_server_transaction_ids = itertools.count(1)


def next_server_transaction_id() -> int:
    return next(_server_transaction_ids)


def response_envelope(
    client_transaction_id: int, value: object = None, error: AlpacaError | None = None
) -> dict:
    envelope = {
        "ClientTransactionID": client_transaction_id,
        "ServerTransactionID": next_server_transaction_id(),
        "ErrorNumber": error.error_number if error else 0,
        "ErrorMessage": error.message if error else "",
    }
    if value is not None:
        envelope["Value"] = value
    return envelope
