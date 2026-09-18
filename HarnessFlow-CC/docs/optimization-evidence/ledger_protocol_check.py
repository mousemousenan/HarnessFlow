# -*- coding: utf-8 -*-
"""Apply OPT-01 ledger reading rules to controlled samples. Evidence helper, not a product test framework."""
from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path

REQUIRED = ("ts", "phase", "batch", "step", "detail")
TZ_AWARE = re.compile(r"(Z|[+-]\d{2}:\d{2})$")


def parse_ts(value: str) -> datetime | None:
    if not isinstance(value, str) or not TZ_AWARE.search(value):
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def read_ledger(path: Path, now: datetime, phase: str) -> dict:
    notes: list[str] = []
    events: list[dict] = []
    if not path.exists():
        return {"usable": False, "reason": "台账恢复不可用：文件不存在", "events": [], "notes": notes, "isolate_newline": False}
    raw = path.read_bytes()
    if not raw:
        return {"usable": False, "reason": "台账恢复不可用：空文件", "events": [], "notes": notes, "isolate_newline": False}

    isolate = not raw.endswith(b"\n")
    text = raw.decode("utf-8")
    lines = text.split("\n")
    if isolate:
        notes.append("尾部半行保留原状；恢复追加前先只追加换行隔离残行")

    for idx, line in enumerate(lines, 1):
        if line == "":
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            notes.append(f"L{idx}: 损坏行已跳过")
            continue
        if not isinstance(obj, dict) or any(k not in obj for k in REQUIRED):
            notes.append(f"L{idx}: 缺字段，已跳过")
            continue
        ts = parse_ts(str(obj.get("ts", "")))
        if ts is None:
            notes.append(f"L{idx}: 非法时间/缺时区，不能作为新鲜心跳")
            continue
        if ts.tzinfo is None:
            notes.append(f"L{idx}: 缺时区")
            continue
        if ts > now:
            notes.append(f"L{idx}: 未来时间，不能作为新鲜心跳")
            continue
        if obj.get("phase") != phase:
            notes.append(f"L{idx}: 旧阶段 {obj.get('phase')}，不作为当前实例心跳")
            continue
        if len(line) > 500:
            notes.append(f"L{idx}: 超过 500 字符，已跳过")
            continue
        events.append(obj)

    started = [e for e in events if e["step"] == "phase_started"]
    if not started:
        return {"usable": False, "reason": "台账恢复不可用：当前阶段无 phase_started 边界", "events": events, "notes": notes, "isolate_newline": isolate}

    boundary = started[-1]
    # current attempt = events from last phase_started inclusive
    bidx = events.index(boundary)
    current = events[bidx:]
    last = current[-1]
    last_ts = parse_ts(last["ts"])
    age_min = (now - last_ts).total_seconds() / 60
    heartbeat_ok = age_min <= 40
    return {
        "usable": True,
        "reason": "",
        "events": current,
        "notes": notes,
        "isolate_newline": isolate,
        "boundary": boundary,
        "last": last,
        "heartbeat_age_min": age_min,
        "heartbeat_ok": heartbeat_ok,
    }


def reconstruct(current: list[dict]) -> dict:
    verified, implemented, pending = [], [], []
    dispatched = set()
    returned = {}
    evidenced = set()
    independently = {}
    for e in current:
        d = e["detail"]
        step = e["step"]
        if step == "worker_dispatched":
            tid = d.split()[0]
            dispatched.add(tid)
        elif step == "worker_returned":
            parts = d.split()
            tid = parts[0]
            returned[tid] = parts[1] if len(parts) > 1 else "?"
        elif step == "verify_command_done":
            evidenced.add(d.split()[0])
        elif step == "verifier_returned":
            parts = d.split()
            independently[parts[0]] = parts[1] if len(parts) > 1 else "?"
    for tid in sorted(dispatched | returned.keys() | evidenced | independently.keys()):
        if independently.get(tid) == "PASS":
            verified.append(tid)
        elif tid in returned or tid in evidenced:
            implemented.append(tid)
        else:
            pending.append(tid)
    return {"verified": verified, "implemented": implemented, "pending": pending}


def log_closed(text: str) -> bool:
    return "start:" in text and "end:" in text and "exit:" in text


def main() -> int:
    here = Path(__file__).resolve().parent / "samples"
    now = datetime.fromisoformat("2026-09-18T16:00:00+08:00")
    cases = []

    healthy = read_ledger(here / "ledger_healthy.jsonl", now, "P01")
    rec = reconstruct(healthy["events"])
    cases.append(("healthy", healthy["usable"] and healthy["heartbeat_ok"] and rec["verified"] == ["P01-T01"], healthy, rec))

    missing = read_ledger(here / "ledger_missing.jsonl", now, "P01")
    cases.append(("missing", (not missing["usable"]) and "不存在" in missing["reason"], missing, None))

    empty = read_ledger(here / "ledger_empty.jsonl", now, "P01")
    cases.append(("empty", (not empty["usable"]) and "空文件" in empty["reason"], empty, None))

    v10 = read_ledger(here / "ledger_v10_truncated.jsonl", now, "P01")
    ok10 = (
        v10["usable"]
        and v10["isolate_newline"]
        and v10["boundary"]["detail"].startswith("attempt=2")
        and v10["heartbeat_ok"]
        and any("缺时区" in n for n in v10["notes"])
        and any("未来时间" in n for n in v10["notes"])
        and any("旧阶段" in n for n in v10["notes"])
        and any("损坏行" in n for n in v10["notes"])
    )
    cases.append(("v10", ok10, v10, reconstruct(v10["events"])))

    complete = (here / "verify-logs" / "P01-T01.log").read_text(encoding="utf-8")
    opened = (here / "verify-logs" / "P01-T02.open.log").read_text(encoding="utf-8")
    log_ok = log_closed(complete) and complete.count("===== attempt=") == 3 and "独立验证结论" in complete
    open_fail = (not log_closed(opened))
    cases.append(("v12_log", log_ok, {"closed": log_closed(complete), "attempts": complete.count("===== attempt=")}, None))
    cases.append(("v13_open_log", open_fail, {"closed": log_closed(opened)}, None))

    sensor = json.loads((here / "sensor-report-P01-B1.json").read_text(encoding="utf-8"))
    sensor_fail = any(v == "fail" for v in sensor["sensors"].values())
    cases.append(("v14_sensor", sensor_fail, sensor, None))

    empty_shell = (here / "empty_shell.py").read_text(encoding="utf-8") == ""
    cases.append(("v14_empty_shell", empty_shell, {"empty": True}, None))

    print("now", now.isoformat())
    failed = 0
    for name, ok, payload, recs in cases:
        status = "PASS" if ok else "FAIL"
        if not ok:
            failed += 1
        print(f"[{status}] {name}")
        if recs:
            print("  reconstruct", recs)
        if isinstance(payload, dict) and payload.get("notes"):
            for n in payload["notes"]:
                print("  note:", n)
        if isinstance(payload, dict) and payload.get("reason"):
            print("  reason:", payload["reason"])
        if isinstance(payload, dict) and "heartbeat_age_min" in payload:
            print("  heartbeat_age_min", round(payload["heartbeat_age_min"], 2), "ok", payload["heartbeat_ok"])
    print("failed", failed)
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
