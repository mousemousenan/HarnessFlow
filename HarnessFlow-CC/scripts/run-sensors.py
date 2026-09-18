#!/usr/bin/env python3
"""Run the seven HarnessFlow sensors and write a JSON report."""

import argparse
import datetime as dt
import json
import sys
import shutil
import subprocess
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")


def run(command: list[str], cwd: Path) -> str | None:
    executable = shutil.which(command[0])
    if executable is None:
        return None
    result = subprocess.run(
        [executable, *command[1:]],
        cwd=cwd,
        capture_output=True,
        text=True,
        check=False,
    )
    return "pass" if result.returncode == 0 else "fail"


def text_sensor(patterns: list[str], files: list[Path]) -> str:
    matches = 0
    for path in files:
        try:
            content = path.read_text(encoding="utf-8")
        except (OSError, UnicodeError):
            continue
        lowered = content.lower()
        if any(pattern in lowered for pattern in patterns):
            matches += 1
    return "warn" if matches else "pass"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("task_id")
    parser.add_argument("--project-root", default=".")
    args = parser.parse_args()

    root = Path(args.project_root).resolve()
    report_path = root / "docs" / "harnessflow" / f"sensor-report-{args.task_id}.json"
    report_path.parent.mkdir(parents=True, exist_ok=True)

    source_files = [
        path
        for directory in ("src", "lib", "scripts", "tests", "test")
        if (root / directory).is_dir()
        for path in (root / directory).rglob("*")
        if path.is_file()
    ]

    correctness = "skip"
    if (root / "package.json").is_file():
        correctness = run(["npm", "test", "--", "--passWithNoTests"], root)
    elif any(root.glob("pytest.ini")) or any(root.glob("pyproject.toml")):
        correctness = run(["pytest"], root)
    elif any(root.glob("go.mod")):
        correctness = run(["go", "test", "./..."], root)

    completeness = text_sensor(["todo", "fixme"], source_files)
    boundary = text_sensor(["empty", "null", "max", "concurrent"], source_files)
    security = text_sensor(["sanitize", "escape", "validate", "auth"], source_files)

    consistency = "skip"
    if (root / ".ruff.toml").is_file() or any(root.glob("pyproject.toml")):
        consistency = run(["ruff", "check", "."], root)

    report = {
        "task_id": args.task_id,
        "timestamp": dt.datetime.now().astimezone().isoformat(),
        "sensors": {
            "correctness": correctness,
            "completeness": completeness,
            "consistency": consistency,
            "boundary": boundary,
            "security": security,
            "performance": "skip",
            "maintainability": "skip",
        },
    }
    report_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"✅ Sensor report saved to {report_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
