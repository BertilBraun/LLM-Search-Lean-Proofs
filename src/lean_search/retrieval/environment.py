"""Which premise names exist in the pinned environment, and their signatures, from one Lean run per shard."""

from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from pathlib import Path

from lean_search.lean.text import lean_string_literal
from lean_search.retrieval.premises import PremiseSignature, one_line, strip_universe_parameters

ERROR_PREFIX = "<error"

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
