"""The pinned environment's constants: which premise names exist, their signatures, theorems LeanDojo lacks."""

import re
from collections.abc import Collection, Iterable, Iterator
from dataclasses import dataclass
from pathlib import Path

from lean_search.lean.text import lean_string_literal
from lean_search.retrieval.premises import PremiseSignature, one_line, strip_universe_parameters

ERROR_PREFIX = "<error"
# Compiler-generated companions of declarations, never written by hand.
_AUXILIARY_LAST_COMPONENT = re.compile(r"^(?:proof_\d+|eq_\d+|match_\d+|sizeOf_spec|inj|injEq)$")
# Metaprogramming libraries: their theorems are about tactics and syntax, not mathematics.
META_NAMESPACES = frozenset(
    {"Lean", "Mathlib", "Aesop", "Qq", "ProofWidgets", "Lake", "Std", "Batteries", "IO", "System", "ImportGraph"}
)

_CONSTANT_SCRIPT = """import Mathlib
open Lean Meta

def leanSearchDumpConstants (outputPath : System.FilePath) : MetaM Unit := do
  let mut lines : Array String := #[]
  for (name, info) in (← getEnv).constants.toList do
    if name.isInternal then continue
    match info with
    | .thmInfo _ => lines := lines.push s!"theorem\\t{name}"
    | .defnInfo _ => lines := lines.push s!"def\\t{name}"
    | _ => pure ()
  IO.FS.writeFile outputPath (String.intercalate "\\n" lines.toList ++ "\\n")

set_option maxHeartbeats 0 in
#eval leanSearchDumpConstants {output}
"""

# Names are compared as `Name.toString`, the form LeanDojo records, so escaped or numeric components need no parsing.
_DUMP_SCRIPT = """import Mathlib
open Lean Meta

def leanSearchDumpSignatures (inputPath outputPath : System.FilePath) : MetaM Unit := do
  let byString : Lean.HashMap String Name :=
    (← getEnv).constants.fold (fun map name _ => map.insert name.toString name) {}
  let mut lines : Array String := #[]
  for requested in ← IO.FS.lines inputPath do
    match byString.find? requested with
    | none => lines := lines.push s!"{requested}\\t0\\t"
    | some name =>
      let signature ← try
          pure ((← PrettyPrinter.ppSignature name).fmt.pretty 1000000)
        catch error => pure s!"<error: {← error.toMessageData.toString}>"
      lines := lines.push s!"{requested}\\t1\\t{(signature.replace "\\n" " ").replace "\\t" " "}"
  IO.FS.writeFile outputPath (String.intercalate "\\n" lines.toList ++ "\\n")

set_option maxHeartbeats 0 in
#eval leanSearchDumpSignatures {input} {output}
"""


@dataclass(frozen=True)
class NameCheck:
    full_name: str
    exists: bool
    # Empty when the name does not exist or Lean could not print it.
    signature: str


@dataclass(frozen=True)
class EnvironmentConstant:
    kind: str
    full_name: str


def constant_dump_script(output_path: Path) -> str:
    return _CONSTANT_SCRIPT.replace("{output}", lean_string_literal(str(output_path)))


def parse_constant_dump(lines: Iterable[str]) -> Iterator[EnvironmentConstant]:
    for line in lines:
        if line.strip():
            kind, full_name = line.rstrip("\n").split("\t", 1)
            yield EnvironmentConstant(kind, full_name)


def is_handwritten_theorem(full_name: str) -> bool:
    return (
        _AUXILIARY_LAST_COMPONENT.match(full_name.rsplit(".", 1)[-1]) is None
        and full_name.split(".", 1)[0] not in META_NAMESPACES
    )


def missing_theorems(constants: Iterable[EnvironmentConstant], known_names: Collection[str]) -> list[str]:
    """Theorems of the environment outside `known_names`, e.g. the `to_additive` and `alias` lemmas LeanDojo lacks."""
    return sorted(
        constant.full_name
        for constant in constants
        if constant.kind == "theorem"
        and constant.full_name not in known_names
        and is_handwritten_theorem(constant.full_name)
    )


def signature_dump_script(names_path: Path, output_path: Path) -> str:
    return _DUMP_SCRIPT.replace("{input}", lean_string_literal(str(names_path))).replace(
        "{output}", lean_string_literal(str(output_path))
    )


def parse_signature_dump(lines: Iterable[str]) -> Iterator[NameCheck]:
    for line in lines:
        if not line.strip():
            continue
        full_name, exists, signature = line.rstrip("\n").split("\t", 2)
        if exists == "0" or signature.startswith(ERROR_PREFIX):
            yield NameCheck(full_name, exists == "1", "")
            continue
        yield NameCheck(full_name, True, strip_universe_parameters(one_line(signature), full_name))


def existing_signatures(checks: Iterable[NameCheck]) -> Iterator[PremiseSignature]:
    for check in checks:
        if check.signature:
            yield PremiseSignature(check.full_name, check.signature)
