"""Tests for snet_tester2 protocol enumerations.

Verifies that enum values match the v1 bare constants they replace,
and that IntEnum members work as plain ints in arithmetic/comparison.
"""

from snet_tester2.protocol.enums import SnetCommand, VarIndex


def test_snet_command_values():
    assert SnetCommand.READ_VAR == 0x0001
    assert SnetCommand.WRITE_VAR == 0x0002
    assert SnetCommand.IO_REQUEST == 0x8000
    assert SnetCommand.IO_RESPONSE == 0x8100


def test_var_index_values():
    assert VarIndex.READ_AD_FLAG == 0x0001
    assert VarIndex.MODE_FLAG == 0x0002
    assert VarIndex.FULL_OPEN_CTRL_FLAG == 0x0003
    assert VarIndex.FULL_OPEN_VALUE == 0x1000


def test_enum_is_int():
    # IntEnum values work as plain ints in arithmetic/comparison
    assert SnetCommand.IO_REQUEST | 0x0100 == 0x8100
    assert int(VarIndex.FULL_OPEN_VALUE) == 0x1000
