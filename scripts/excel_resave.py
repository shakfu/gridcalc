"""Copy workbooks into OUT and have Excel for Mac recalculate and save each one.

    uv run python scripts/excel_resave.py --list sample.txt --out saved/

One `osascript` call per file, with a time limit; on a hang Excel is killed
and the file is logged as failed. `OUT/resave.jsonl` logs every file, so a
rerun skips those done. A file Excel will not open fails with "Parameter
error (-50)": with alerts off, Excel opens no workbook to save.

A file with external links still shows Excel's "update links" prompt; click
"Don't update". Results: `docs/dev/comparison.md`.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import time
from pathlib import Path

_SCRIPT = """
tell application id "com.microsoft.Excel"
    set display alerts to false
    open POSIX file "{path}"
    set wb to active workbook
    calculate full rebuild
    save wb
    close wb saving no
end tell
"""


def _kill_excel() -> None:
    subprocess.run(["pkill", "-9", "-f", "Microsoft Excel.app"], check=False)  # noqa: S607
    time.sleep(3)


def resave(src: Path, out: Path, timeout: float) -> dict[str, object]:
    """Copy ``src`` into ``out`` under a hashed name and save it through Excel."""
    dst = (out / (hashlib.sha1(str(src).encode()).hexdigest()[:12] + ".xlsx")).resolve()  # noqa: S324
    shutil.copyfile(src, dst)
    rec: dict[str, object] = {"src": str(src), "dst": str(dst)}
    t = time.monotonic()
    try:
        r = subprocess.run(  # noqa: S603
            ["osascript", "-e", _SCRIPT.format(path=dst)],  # noqa: S607
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
        rec["ok"] = r.returncode == 0
        if r.returncode:
            rec["err"] = r.stderr.strip()[:300]
    except subprocess.TimeoutExpired:
        rec.update(ok=False, err="timeout")
        _kill_excel()
    rec["s"] = round(time.monotonic() - t, 1)
    return rec


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--list", type=Path, required=True, help="one workbook path per line")
    p.add_argument("--out", type=Path, required=True)
    p.add_argument("--timeout", type=float, default=120, help="seconds per file")
    a = p.parse_args()
    a.out.mkdir(parents=True, exist_ok=True)
    log = a.out / "resave.jsonl"
    done = {json.loads(x)["src"] for x in log.read_text().splitlines()} if log.exists() else set()
    for line in a.list.read_text().splitlines():
        src = Path(line.strip())
        if not line.strip() or str(src) in done:
            continue
        rec = resave(src, a.out, a.timeout)
        with log.open("a") as f:
            f.write(json.dumps(rec) + "\n")
        print(
            ("ok  " if rec["ok"] else "FAIL") + f" {rec['s']:6.1f}s {src.name} {rec.get('err', '')}"
        )


if __name__ == "__main__":
    main()
