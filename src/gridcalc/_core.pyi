"""Type stubs for the nanobind-built _core extension."""

from typing import Any

def xlsx_read(
    path: str,
) -> tuple[list[str], list[tuple[str, int, int, str, Any, str, int]], int]: ...
def xlsx_write(path: str, cells: list[tuple[Any, ...]], sheet_names: list[str] = ...) -> None: ...
