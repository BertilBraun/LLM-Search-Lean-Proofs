"""An arm's (or step 2's shared sampling run's) loop and phase configs from its thin overlay
(src/lean_search/rl/study_configs.py; DESIGN.md, "Follow-up study: controlled arms", "Arms", "Step 2").

    python experiments/followup_arm.py --mode experiments/configs/grpo/followup/modes/visible.toml \
        --arm experiments/configs/grpo/followup/arms/A.toml --output $LEAN_SEARCH_RUNS/followup_configs
    python experiments/followup_arm.py --mode /workspace/runs/study_chain/mode.toml \
        --arm experiments/configs/grpo/followup/arms/C.toml --output $LEAN_SEARCH_RUNS/followup_configs
    python experiments/followup_arm.py --kind "shared sampling" --mode /workspace/runs/study_chain/mode.toml \
        --arm experiments/configs/grpo/followup/shared_sampling.toml --output $LEAN_SEARCH_RUNS/followup_configs

--mode is the sampling mode (followup/modes/: the search config and the expansions per training search), the same file
for the shared sampling run and every arm. Writes <output>/<name>/loop.toml (followup/base.toml in that mode, with the
overlay's [loop] lines, its training.phase_config pointing at the file beside it) and <output>/<name>/phase.toml
(base.toml's phase template with the overlay's [phase] lines), loads both back and prints the path of loop.toml. An arm
whose policy trains in expert-iteration rounds (C, D) also gets <output>/<name>/expert_iteration.toml
(followup/expert_iteration.toml with the overlay's [expert_iteration] lines), which its loop config names. Refuses an
overlay that changes anything but its kind's settings (an arm: name, seed offset, credit mode, learning rate, the
rounds' schedule, window and learning rate; the shared sampling: name, the phase and total token budgets), one that
still holds a PLACEHOLDER, a mode that sets anything but the search config and the expansions or whose search config
does not load or caps each search's generated tokens, an arm whose sampling differs from step 2's shared run's (its
sampling.json: the search config, the expansions and the search config's sha256, written beside every loop.toml), an
arm whose loop config has no phase_generated_tokens or max_phases (its phases would end on minutes and groups), a
shared sampling run whose phase would come due, and an existing <output>/<name> with other contents (the same contents
are written again silently, so a restart can rerun it). deployment/arm_loop.sh starts the loop from it.
"""

import argparse
import json
import shutil
import sys
import tomllib
from pathlib import Path

from lean_search.expert_iteration.toml_text import toml_text
from lean_search.rl.expert_iteration_data import parse_expert_iteration_config
from lean_search.rl.loop_config import load_loop_config
from lean_search.rl.study_configs import (
    SAMPLING_RECORD_FILE,
    OverlayKind,
    SamplingRecord,
    overlay_configs,
    sampling_record,
    sampling_refusal,
    training_search_refusal,
    with_sampling_mode,
)
from lean_search.rl.training_phase import TrainingPhaseConfig
from lean_search.search import load_run_config
from lean_search.search.records import from_json_object, to_json

REPOSITORY_DIRECTORY = Path(__file__).resolve().parents[1]
BASE = "experiments/configs/grpo/followup/base.toml"
EXPERT_ITERATION_RECIPE = "experiments/configs/grpo/followup/expert_iteration.toml"
SHARED_SAMPLING = "experiments/configs/grpo/followup/shared_sampling.toml"


def parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--arm", type=Path, required=True, help="the overlay")
    parser.add_argument("--kind", type=OverlayKind, choices=list(OverlayKind), default=OverlayKind.ARM)
    parser.add_argument("--mode", type=Path, required=True, help="the sampling mode (followup/modes/)")
    parser.add_argument("--output", type=Path, required=True)
    return parser.parse_args()


def read_toml(path: Path) -> dict:
    return tomllib.loads(path.read_text(encoding="utf-8"))


def mode_base(mode: Path) -> dict:
    """base.toml in the mode; SystemExit for a mode that changes more, or whose search config does not load or is
    an evaluation's."""
    try:
        base = with_sampling_mode(read_toml(REPOSITORY_DIRECTORY / BASE), read_toml(mode))
        refusal = training_search_refusal(load_run_config(REPOSITORY_DIRECTORY / base["sampling"]["search_config"]))
    except (ValueError, OSError) as error:
        raise SystemExit(f"{mode}: {error}") from error
    if refusal is not None:
        raise SystemExit(f"{mode}: {refusal}")
    return base


def shared_sampling_refusal(output: Path, record: SamplingRecord) -> str | None:
    """Against step 2's shared run, once it has configs under `output`: its sampling record, or for configs written
    without one its loop.toml's search config path and expansions."""
    shared = output / read_toml(REPOSITORY_DIRECTORY / SHARED_SAMPLING)["loop"]["name"]
    if not (shared / "loop.toml").exists():
        return None
    if (shared / SAMPLING_RECORD_FILE).exists():
        recorded = json.loads((shared / SAMPLING_RECORD_FILE).read_text(encoding="utf-8"))
        return sampling_refusal(record, from_json_object(SamplingRecord, recorded))
    sampling = read_toml(shared / "loop.toml")["sampling"]
    expected = SamplingRecord(sampling["search_config"], sampling["max_expansions"], record.search_config_sha256)
    return sampling_refusal(record, expected)


def write_directory(directory: Path, texts: dict[str, str]) -> None:
    """All files or none: written beside it and renamed into place, so a kill mid-write leaves no partial directory
    that later starts would refuse as holding other configs. A staging directory a killed start left is replaced."""
    staging = directory.with_name(f".{directory.name}.staging")
    if staging.exists():
        shutil.rmtree(staging)
    staging.mkdir(parents=True)
    for name, text in texts.items():
        (staging / name).write_text(text, encoding="utf-8")
    staging.rename(directory)


def main() -> None:
    arguments = parse_arguments()
    overlay = read_toml(arguments.arm)
    base = mode_base(arguments.mode)
    record = sampling_record(base["sampling"], REPOSITORY_DIRECTORY)
    if arguments.kind == OverlayKind.ARM:
        refusal = shared_sampling_refusal(arguments.output.absolute(), record)
        if refusal is not None:
            raise SystemExit(f"{arguments.arm}: {refusal}.")
    phase_template = read_toml(REPOSITORY_DIRECTORY / base["training"]["phase_config"])
    directory = arguments.output.absolute() / overlay["loop"]["name"]
    try:
        configs = overlay_configs(
            arguments.kind,
            overlay,
            base,
            phase_template,
            str(directory / "phase.toml"),
            read_toml(REPOSITORY_DIRECTORY / EXPERT_ITERATION_RECIPE),
            str(directory / "expert_iteration.toml"),
        )
    except ValueError as error:
        raise SystemExit(f"{arguments.arm}: {error}") from error
    texts = {
        "phase.toml": toml_text(configs.phase),
        "loop.toml": toml_text(configs.loop),
        SAMPLING_RECORD_FILE: to_json(record) + "\n",
    }
    if configs.expert_iteration is not None:
        texts["expert_iteration.toml"] = toml_text(configs.expert_iteration)
    if directory.exists():
        differing = [
            name
            for name, text in texts.items()
            if not (directory / name).exists() or (directory / name).read_text(encoding="utf-8") != text
        ]
        if differing:
            raise SystemExit(f"{directory} holds other {differing}: an arm's configs are written once.")
    else:
        write_directory(directory, texts)
    load_loop_config(directory / "loop.toml")
    from_json_object(TrainingPhaseConfig, read_toml(directory / "phase.toml"))
    if configs.expert_iteration is not None:
        parse_expert_iteration_config((directory / "expert_iteration.toml").read_text(encoding="utf-8"))
    print(f"{directory}/loop.toml", flush=True)
    print(f"Wrote {', '.join(f'{directory}/{name}' for name in texts)}.", file=sys.stderr)


if __name__ == "__main__":
    main()
