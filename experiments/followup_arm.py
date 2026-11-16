"""An arm's (or step 2's shared sampling run's) loop and phase configs from its thin overlay
(src/lean_search/rl/study_configs.py; DESIGN.md, "Follow-up study: controlled arms", "Arms", "Step 2").

    python experiments/followup_arm.py --arm experiments/configs/grpo/followup/arms/A.toml \
        --output $LEAN_SEARCH_RUNS/followup_configs
    python experiments/followup_arm.py --arm experiments/configs/grpo/followup/arms/C.toml \
        --output $LEAN_SEARCH_RUNS/followup_configs
    python experiments/followup_arm.py --kind "shared sampling" \
        --arm experiments/configs/grpo/followup/shared_sampling.toml --output $LEAN_SEARCH_RUNS/followup_configs

Writes <output>/<name>/loop.toml (followup/base.toml with the overlay's [loop] lines, its training.phase_config
pointing at the file beside it) and <output>/<name>/phase.toml (base.toml's phase template with the overlay's [phase]
lines), loads both back and prints the path of loop.toml. An arm whose policy trains in expert-iteration rounds (C, D)
also gets <output>/<name>/expert_iteration.toml (followup/expert_iteration.toml with the overlay's [expert_iteration]
lines), which its loop config names. Refuses an overlay that changes anything but its kind's settings (an arm: name,
seed offset, credit mode, learning rate, the rounds' schedule, window and learning rate; the shared sampling: name, the
phase and total token budgets), one that still holds a PLACEHOLDER, an arm whose loop config has no
phase_generated_tokens or max_phases (its phases would end on minutes and groups), a shared sampling run whose phase
would come due, and an existing <output>/<name> with other contents (the same contents are written again silently, so a
restart can rerun it). deployment/arm_loop.sh starts the loop from it.
"""

import argparse
import sys
import tomllib
from pathlib import Path

from lean_search.expert_iteration.toml_text import toml_text
from lean_search.rl.expert_iteration_data import parse_expert_iteration_config
from lean_search.rl.loop_config import load_loop_config
from lean_search.rl.study_configs import OverlayKind, overlay_configs
from lean_search.rl.training_phase import TrainingPhaseConfig
from lean_search.search.records import from_json_object

REPOSITORY_DIRECTORY = Path(__file__).resolve().parents[1]
BASE = "experiments/configs/grpo/followup/base.toml"
EXPERT_ITERATION_RECIPE = "experiments/configs/grpo/followup/expert_iteration.toml"


def parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--arm", type=Path, required=True, help="the overlay")
    parser.add_argument("--kind", type=OverlayKind, choices=list(OverlayKind), default=OverlayKind.ARM)
    parser.add_argument("--output", type=Path, required=True)
    return parser.parse_args()


def read_toml(path: Path) -> dict:
    return tomllib.loads(path.read_text(encoding="utf-8"))


def main() -> None:
    arguments = parse_arguments()
    overlay = read_toml(arguments.arm)
    base = read_toml(REPOSITORY_DIRECTORY / BASE)
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
    texts = {"phase.toml": toml_text(configs.phase), "loop.toml": toml_text(configs.loop)}
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
        directory.mkdir(parents=True)
        for name, text in texts.items():
            (directory / name).write_text(text, encoding="utf-8")
    load_loop_config(directory / "loop.toml")
    from_json_object(TrainingPhaseConfig, read_toml(directory / "phase.toml"))
    if configs.expert_iteration is not None:
        parse_expert_iteration_config((directory / "expert_iteration.toml").read_text(encoding="utf-8"))
    print(f"{directory}/loop.toml", flush=True)
    print(f"Wrote {', '.join(f'{directory}/{name}' for name in texts)}.", file=sys.stderr)


if __name__ == "__main__":
    main()
