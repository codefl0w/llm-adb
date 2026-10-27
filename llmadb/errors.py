"""Error definitions and exit codes for llmadb."""

from typing import Optional


# Exit codes
EXIT_OK = 0
EXIT_GENERIC = 1
EXIT_USAGE = 2
EXIT_DEVICE_SELECTION = 3
EXIT_DEVICE_STATE = 4
EXIT_TIMEOUT = 5
EXIT_NOT_FOUND = 6
EXIT_SECURE_OR_EMPTY = 7
EXIT_ADB = 8

# Standard Error Codes
E_NO_DEVICE = "E_NO_DEVICE"
E_MULTI_DEVICE = "E_MULTI_DEVICE"
E_DEVICE_STATE = "E_DEVICE_STATE"
E_TIMEOUT = "E_TIMEOUT"
E_NOT_FOUND = "E_NOT_FOUND"
E_AMBIGUOUS = "E_AMBIGUOUS"
E_SECURE_OR_EMPTY = "E_SECURE_OR_EMPTY"
E_UNSUPPORTED = "E_UNSUPPORTED"
E_USAGE = "E_USAGE"
E_ADB = "E_ADB"

DEFAULT_EXIT_CODES = {
    E_NO_DEVICE: EXIT_DEVICE_SELECTION,
    E_MULTI_DEVICE: EXIT_DEVICE_SELECTION,
    E_DEVICE_STATE: EXIT_DEVICE_STATE,
    E_TIMEOUT: EXIT_TIMEOUT,
    E_NOT_FOUND: EXIT_NOT_FOUND,
    E_AMBIGUOUS: EXIT_NOT_FOUND,
    E_SECURE_OR_EMPTY: EXIT_SECURE_OR_EMPTY,
    E_UNSUPPORTED: EXIT_USAGE,
    E_USAGE: EXIT_USAGE,
    E_ADB: EXIT_ADB,
}


class LlmadbError(Exception):
    """Base structured exception for llmadb.
    
    Produces output format:
      error: <CODE> <message> | hint: <hint>
    """

    def __init__(
        self,
        code: str,
        message: str,
        hint: str,
        exit_code: Optional[int] = None,
    ):
        super().__init__(message)
        self.code = code
        self.message = message
        self.hint = hint
        self.exit_code = (
            exit_code if exit_code is not None else DEFAULT_EXIT_CODES.get(code, EXIT_GENERIC)
        )

    def format_line(self) -> str:
        return f"error: {self.code} {self.message} | hint: {self.hint}"

    def __str__(self) -> str:
        return self.format_line()
