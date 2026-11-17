"""A stand-in for the Lean REPL binary speaking its JSON protocol, for process tests without Lean.

Tactics (after the search's heartbeat wrapper): `hang` never answers, `fail` is a Lean error, `done` closes the goal,
anything else reaches a new state with the goal unchanged. Imports take FAKE_REPL_IMPORT_SECONDS. Every request is
appended to FAKE_REPL_LOG as `<pid>\t<cmd|tactic>\t<text>`.
"""

import json
import os
import sys
import time

GOAL = "⊢ True"


def log(kind: str, text: str) -> None:
    with open(os.environ["FAKE_REPL_LOG"], "a", encoding="utf-8") as handle:
        handle.write(f"{os.getpid()}\t{kind}\t{json.dumps(text)}\n")


def unwrapped(tactic: str) -> str:
    if tactic.startswith("lean_search_heartbeats "):
        return tactic.split("=>", 1)[1].strip()
    return tactic


def answer(request: dict[str, object], counters: dict[str, int]) -> dict[str, object] | None:
    if "cmd" in request:
        command = str(request["cmd"])
        log("cmd", command)
        if command.startswith("import"):
            time.sleep(float(os.environ.get("FAKE_REPL_IMPORT_SECONDS", "0")))
        counters["env"] += 1
        response: dict[str, object] = {"env": counters["env"]}
        if command.startswith("theorem") and "sorry" in command:
            counters["state"] += 1
            response["sorries"] = [{"goal": GOAL, "proofState": counters["state"]}]
        if command.startswith("#print axioms _root_."):
            name = command.removeprefix("#print axioms _root_.")
            response["messages"] = [{"severity": "info", "data": f"'{name}' does not depend on any axioms"}]
        return response
    tactic = unwrapped(str(request["tactic"]))
    log("tactic", tactic)
    match tactic:
        case "hang":
            time.sleep(3600)
            return None
        case "fail":
            return {"message": "Lean error:\nlinarith failed"}
    counters["state"] += 1
    return {"proofState": counters["state"], "goals": [] if tactic == "done" else [GOAL]}


def main() -> None:
    counters = {"env": 0, "state": 0}
    lines: list[str] = []
    for line in sys.stdin:
        if line.strip():
            lines.append(line)
            continue
        if not lines:
            continue
        response = answer(json.loads("".join(lines)), counters)
        lines = []
        if response is not None:
            sys.stdout.write(json.dumps(response, ensure_ascii=False) + "\n\n")
            sys.stdout.flush()


if __name__ == "__main__":
    main()
