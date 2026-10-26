"""The file fields of the entities in the bindings (ADR 0027)."""

from appgen.dsl.model import AppDefinition
from appgen.dsl.storage import file_fields
from appgen.gen.render import GenerationError


def reject_file_fields(definition: AppDefinition, binding: str) -> None:
    """Raise GenerationError if the definition has a file field.

    The bindings add the file fields one after the other. A binding calls
    this function until it generates the code of the file fields.
    """
    for field in file_fields(definition):
        raise GenerationError(
            f"The binding '{binding}' does not generate '{field.type}' fields yet: '{field.id}'."
        )
