"""Tests for structured errors and exit codes."""

from llmadb.errors import (
    E_ADB,
    E_DEVICE_STATE,
    E_MULTI_DEVICE,
    E_NO_DEVICE,
    E_NOT_FOUND,
    E_SECURE_OR_EMPTY,
    E_TIMEOUT,
    E_USAGE,
    EXIT_ADB,
    EXIT_DEVICE_SELECTION,
    EXIT_DEVICE_STATE,
    EXIT_NOT_FOUND,
    EXIT_SECURE_OR_EMPTY,
    EXIT_TIMEOUT,
    EXIT_USAGE,
    LlmadbError,
)


def test_error_format():
    err = LlmadbError(
        code=E_NO_DEVICE,
        message="no devices connected",
        hint="check USB, enable USB debugging",
    )
    assert err.format_line() == "error: E_NO_DEVICE no devices connected | hint: check USB, enable USB debugging"
    assert str(err) == err.format_line()
    assert err.exit_code == EXIT_DEVICE_SELECTION


def test_exit_codes_mapping():
    assert LlmadbError(E_NO_DEVICE, "", "").exit_code == EXIT_DEVICE_SELECTION
    assert LlmadbError(E_MULTI_DEVICE, "", "").exit_code == EXIT_DEVICE_SELECTION
    assert LlmadbError(E_DEVICE_STATE, "", "").exit_code == EXIT_DEVICE_STATE
    assert LlmadbError(E_TIMEOUT, "", "").exit_code == EXIT_TIMEOUT
    assert LlmadbError(E_NOT_FOUND, "", "").exit_code == EXIT_NOT_FOUND
    assert LlmadbError(E_SECURE_OR_EMPTY, "", "").exit_code == EXIT_SECURE_OR_EMPTY
    assert LlmadbError(E_USAGE, "", "").exit_code == EXIT_USAGE
    assert LlmadbError(E_ADB, "", "").exit_code == EXIT_ADB
