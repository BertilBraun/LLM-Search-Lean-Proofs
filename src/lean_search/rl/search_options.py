"""The search options under measurement (policy/README.md): the set a harness variant or the loop's options arm turns
on, the evaluations' template with all of them off, and the loop's A/B arm of a statement."""

import dataclasses
import hashlib
from dataclasses import dataclass, field

from lean_search.policy.config import FeedbackConfig
from lean_search.search import RunConfig
from lean_search.search.search import NameRepairConfig

CONTROL_ARM = "control"


@dataclass(frozen=True)
class SearchOptions:
    # None keeps the template's.
    temperature: float | None = None
    feedback: FeedbackConfig = field(default_factory=FeedbackConfig)
    # Turns the template's overlap off: the sweep must finish before the request names its failures.
    failed_automation_in_prompt: bool = False
    name_repair: NameRepairConfig = field(default_factory=NameRepairConfig)


def with_search_options(template: RunConfig, options: SearchOptions) -> RunConfig:
    temperature = template.policy.temperature if options.temperature is None else options.temperature
    policy = dataclasses.replace(
        template.policy,
        temperature=temperature,
        feedback=options.feedback,
        failed_automation_in_prompt=options.failed_automation_in_prompt,
    )
    search = dataclasses.replace(template.search, name_repair=options.name_repair)
    expander = (
        dataclasses.replace(template.expander, overlap=False)
        if options.failed_automation_in_prompt
        else template.expander
    )
    return dataclasses.replace(template, policy=policy, search=search, expander=expander)


def without_search_options(template: RunConfig) -> RunConfig:
    """Every option off, at the template's temperature: the loop's evaluations search with this whatever its sampling
    enables, so that version 0's baselines stay comparable."""
    return with_search_options(template, SearchOptions())


@dataclass(frozen=True)
class OptionsArmConfig:
    """The in-loop A/B: statements whose sha256(name) is odd search with `options` (the arm `name`), the others with
    the search template as it is (`control`). An empty name turns it off, and so does the loop once statements were
    started with it in `max_phases` phases (0: never; rl/options_ab.py)."""

    name: str = ""
    options: SearchOptions = field(default_factory=SearchOptions)
    max_phases: int = 0


def search_arm(config: OptionsArmConfig, problem_name: str) -> str:
    """The statement's arm; "" with the A/B off."""
    if not config.name:
        return ""
    return config.name if hashlib.sha256(problem_name.encode()).digest()[-1] % 2 else CONTROL_ARM
