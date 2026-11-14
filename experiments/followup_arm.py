"""An arm's loop and phase configs from its thin file (src/lean_search/rl/study_configs.py; DESIGN.md, "Follow-up study:
controlled arms", "Arms").

    python experiments/followup_arm.py --arm experiments/configs/grpo/followup/arms/A.toml \
        --output $LEAN_SEARCH_RUNS/followup_configs

Writes <output>/<name>/loop.toml (followup/base.toml with the arm's [loop] lines, its training.phase_config pointing
at the file beside it) and <output>/<name>/phase.toml (base.toml's phase template with the arm's [phase] lines), then
prints the loop's commands. Refuses an arm that changes anything but its credit mode, learning rate, seed offset and
name, one that still holds a PLACEHOLDER, and an existing <output>/<name>.
"""

import argparse
import tomllib
from pathlib import Path

from lean_search.expert_iteration.toml_text import toml_text
from lean_search.rl.loop_config import load_loop_config
from lean_search.rl.study_configs import arm_configs
from lean_search.rl.training_phase import TrainingPhaseConfig
from lean_search.search.records import from_json_object

REPOSITORY_DIRECTORY = Path(__file__).resolve().parents[1]
BASE = "experiments/configs/grpo/followup/base.toml"


def parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--arm", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    return parser.parse_args()


def read_toml(path: Path) -> dict:
    return tomllib.loads(path.read_text(encoding="utf-8"))


def main() -> None:
    arguments = parse_arguments()
    arm = read_toml(arguments.arm)
    base = read_toml(REPOSITORY_DIRECTORY / BASE)
    phase_template = read_toml(REPOSITORY_DIRECTORY / base["training"]["phase_config"])
    directory = arguments.output.absolute() / arm["loop"]["name"]
    try:
        configs = arm_configs(arm, base, phase_template, str(directory / "phase.toml"))
    except ValueError as error:
        raise SystemExit(f"{arguments.arm}: {error}") from error
    if directory.exists():
        raise SystemExit(f"{directory} exists: an arm's configs are written once.")
    directory.mkdir(parents=True)
    (directory / "phase.toml").write_text(toml_text(configs.phase), encoding="utf-8")
    (directory / "loop.toml").write_text(toml_text(configs.loop), encoding="utf-8")
    load_loop_config(directory / "loop.toml")
    from_json_object(TrainingPhaseConfig, read_toml(directory / "phase.toml"))
    print(f"Wrote {directory}/loop.toml and phase.toml; the loop:")
    print(f"  python experiments/grpo_loop.py --config {directory}/loop.toml init")
    print(f"  LOOP_CONFIG={directory}/loop.toml deployment/grpo_loop.sh loop")


if __name__ == "__main__":
    main()
