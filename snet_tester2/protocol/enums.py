"""SNET protocol enumerations.

Centralizes command codes and variable indices that were previously
scattered as bare constants in constants.py.
"""

from enum import IntEnum


class SnetCommand(IntEnum):
    READ_VAR    = 0x0001
    WRITE_VAR   = 0x0002
    IO_REQUEST  = 0x8000
    IO_RESPONSE = 0x8100


class VarIndex(IntEnum):
    READ_AD_FLAG         = 0x0001
    MODE_FLAG            = 0x0002
    FULL_OPEN_CTRL_FLAG  = 0x0003
    FULL_OPEN_VALUE      = 0x1000
