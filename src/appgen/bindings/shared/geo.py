"""The `point` fields of the entities in the bindings (ADR 0046)."""

from appgen.dsl.model import AppDefinition
from appgen.gen.render import GenerationError


def reject_point_fields(definition: AppDefinition, binding: str) -> None:
    """Raise GenerationError if an entity has a `point` field.

    The bindings add the point fields one after the other. A binding calls
    this function until it generates the code of the point fields.
    """
    for entity in definition.entities.values():
        for field in entity.fields.values():
            if field.is_point:
                raise GenerationError(
                    f"The binding '{binding}' does not generate 'point' fields yet: '{field.id}'."
                )
