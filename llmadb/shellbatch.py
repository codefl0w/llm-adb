"""Batch multiple adb shell commands into a single round-trip using delimiters."""

from typing import Dict, List, Optional, Tuple

from llmadb.adb import Adb

DELIM_PREFIX = "___LLMADB_BATCH_"
DELIM_SUFFIX = "___"


def run_batch(
    adb: Adb,
    commands: Dict[str, str],
    serial: Optional[str] = None,
    timeout: Optional[float] = 10.0,
) -> Dict[str, str]:
    """Execute multiple shell commands in one adb shell call.
    
    Args:
      adb: Adb runner instance.
      commands: Dict mapping key name to shell command string.
      serial: Target device serial.
      timeout: Command timeout.
      
    Returns:
      Dict mapping key name to trimmed output string.
    """
    if not commands:
        return {}

    # Build shell script combining commands separated by unique delimiters
    script_parts: List[str] = []
    for key, cmd in commands.items():
        delimiter = f"{DELIM_PREFIX}{key}{DELIM_SUFFIX}"
        script_parts.append(f"echo '{delimiter}'")
        script_parts.append(cmd)

    full_script = "; ".join(script_parts)
    res = adb.run(["shell", full_script], serial=serial, timeout=timeout)
    stdout = res.text

    outputs: Dict[str, str] = {}
    keys = list(commands.keys())

    for idx, key in enumerate(keys):
        delimiter = f"{DELIM_PREFIX}{key}{DELIM_SUFFIX}"
        pos = stdout.find(delimiter)
        if pos == -1:
            outputs[key] = ""
            continue

        start = pos + len(delimiter)
        # Next delimiter marks end
        if idx + 1 < len(keys):
            next_key = keys[idx + 1]
            next_delim = f"{DELIM_PREFIX}{next_key}{DELIM_SUFFIX}"
            end = stdout.find(next_delim, start)
            chunk = stdout[start:end] if end != -1 else stdout[start:]
        else:
            chunk = stdout[start:]

        outputs[key] = chunk.strip()

    return outputs
