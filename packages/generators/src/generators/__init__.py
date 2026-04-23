"""Per-pattern transformation generators.

Each generator implements the `PatternGenerator` Protocol: takes a
`MappingProposal` + a `GenerationContext`, returns a `MappingSpec` with the
generated SQL + appropriate dbt test assertions.

M1 exports three generators: rename, concat, derived. The other six live as
placeholders in the Pattern enum (UNSUPPORTED_IN_M1) and will land in later
milestones.
"""

from generators.base import GenerationContext, PatternGenerator
from generators.concat import ConcatGenerator
from generators.derived import DerivedGenerator
from generators.rename import RenameGenerator

__all__ = [
    "ConcatGenerator",
    "DerivedGenerator",
    "GenerationContext",
    "PatternGenerator",
    "RenameGenerator",
]
