"""Low-level adb execution and process wrapper."""

import os
import shutil
import subprocess
from dataclasses import dataclass
from typing import List, Optional

from llmadb.errors import E_ADB, E_TIMEOUT, LlmadbError


@dataclass
class Result:
    stdout: bytes
    stderr: bytes
    code: int

    @property
    def text(self) -> str:
        return self.stdout.decode("utf-8", errors="replace")

    @property
    def stderr_text(self) -> str:
        return self.stderr.decode("utf-8", errors="replace")


def clean_adb_output(data: bytes) -> bytes:
    """Strip ADB daemon startup messages from output."""
    lines = []
    for line in data.splitlines(keepends=True):
        stripped = line.lstrip()
        if stripped.startswith(b"* daemon "):
            continue
        lines.append(line)
    return b"".join(lines)


class Adb:
    """Wrapper for running adb commands with binary safety."""

    def __init__(self, adb_path: Optional[str] = None, default_timeout: Optional[float] = None):
        self.adb_path = (
            adb_path
            or os.environ.get("LLMADB_ADB")
            or shutil.which("adb")
            or "adb"
        )
        self.default_timeout = default_timeout

    def build_cmd(self, args: List[str], serial: Optional[str] = None) -> List[str]:
        cmd = [self.adb_path]
        if serial:
            cmd.extend(["-s", serial])
        cmd.extend(args)
        return cmd

    def run(
        self,
        args: List[str],
        serial: Optional[str] = None,
        timeout: Optional[float] = None,
        binary: bool = True,
        check: bool = False,
    ) -> Result:
        effective_timeout = self.default_timeout if self.default_timeout is not None else timeout
        cmd = self.build_cmd(args, serial=serial)
        try:
            proc = subprocess.run(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=effective_timeout,
                shell=False,
            )
        except subprocess.TimeoutExpired as e:
            raise LlmadbError(
                code=E_TIMEOUT,
                message=f"adb command timed out after {effective_timeout}s: {' '.join(cmd)}",
                hint="increase timeout with --timeout or check device responsiveness",
            ) from e
        except FileNotFoundError as e:
            raise LlmadbError(
                code=E_ADB,
                message=f"adb binary not found at '{self.adb_path}'",
                hint="install Android platform-tools or set LLMADB_ADB",
            ) from e
        except OSError as e:
            raise LlmadbError(
                code=E_ADB,
                message=f"failed to execute adb: {e}",
                hint="verify adb binary permissions and path",
            ) from e

        stdout = clean_adb_output(proc.stdout)
        stderr = clean_adb_output(proc.stderr)

        if check and proc.returncode != 0:
            err_msg = stderr.decode("utf-8", errors="replace").strip() or f"exit code {proc.returncode}"
            raise LlmadbError(
                code=E_ADB,
                message=f"adb failed: {err_msg}",
                hint="check adb connection or command arguments",
            )

        return Result(stdout=stdout, stderr=stderr, code=proc.returncode)

    def exec_passthrough(
        self,
        args: List[str],
        serial: Optional[str] = None,
    ) -> int:
        """Run adb with inherited stdio for byte-identical passthrough."""
        cmd = self.build_cmd(args, serial=serial)
        try:
            proc = subprocess.run(cmd, shell=False)
            return proc.returncode
        except FileNotFoundError as e:
            raise LlmadbError(
                code=E_ADB,
                message=f"adb binary not found at '{self.adb_path}'",
                hint="install Android platform-tools or set LLMADB_ADB",
            ) from e
        except OSError as e:
            raise LlmadbError(
                code=E_ADB,
                message=f"failed to execute adb: {e}",
                hint="verify adb binary permissions and path",
            ) from e
