"""Handler for 'clear-cache' command: purge temporary screenshots and snapshots."""

import sys
from typing import List, Optional

from llmadb.adb import Adb
from llmadb.cache import clear_cache, format_byte_size
from llmadb.errors import E_USAGE, EXIT_USAGE, LlmadbError


def run_clear_cache(
    args: List[str],
    adb: Adb,
    serial: Optional[str] = None,
    max_lines: Optional[int] = None,
) -> int:
    """Execute 'clear-cache' command."""
    all_data = False
    for a in args:
        if a == "--all":
            all_data = True
        else:
            raise LlmadbError(
                code=E_USAGE,
                message=f"unknown clear-cache option '{a}'",
                hint="usage: llmadb clear-cache [--all]",
                exit_code=EXIT_USAGE,
            )

    count, total_bytes = clear_cache(serial=serial, all_data=all_data)
    sys.stdout.write(f"cleared {count} files ({format_byte_size(total_bytes)})\n")
    sys.stdout.flush()
    return 0
