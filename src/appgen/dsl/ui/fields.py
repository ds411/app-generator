"""Field paths: the fields and relations that UI elements show (ADR 0003).

A field path starts at an entity. Each segment before the last is a
`many_to_one` or a `one_to_one` relation. The last segment is a field, a
relation, or `id`, the implicit primary key.
"""

from collections.abc import Collection
from dataclasses import dataclass

from appgen.dsl.model import AppDefinition, Entity, Field, Relation

SINGLE_KINDS = frozenset({"many_to_one", "one_to_one"})
NUMBER_TYPES = frozenset({"integer", "decimal"})
DATE_TYPES = frozenset({"date", "datetime"})
TEXT_TYPES = frozenset({"string", "text", "email"})


@dataclass(frozen=True, slots=True)
class FieldTarget:
    """The field or relation at the end of a field path."""

    entity: str
    """The entity that has the field or the relation."""
    name: str
    member: Field | Relation | None
    """None for `id`."""

    @property
    def type(self) -> str:
        """The field type, `relation`, or `uuid` for `id`."""
        if isinstance(self.member, Field):
            return self.member.type
        return "uuid" if self.member is None else "relation"

    @property
    def relation_kind(self) -> str | None:
        return self.member.kind if isinstance(self.member, Relation) else None

    @property
    def enum_values(self) -> list[str]:
        if isinstance(self.member, Field) and self.member.type == "enum":
            return list(self.member.values or [])
        return []

    def is_one_of(self, types: Collection[str]) -> bool:
        """Return true if the type or the relation kind is in a set of types and kinds."""
        return self.type in types or (self.relation_kind or "") in types


class FieldPathError(Exception):
    """A field path that does not resolve. The message says why."""


def resolve_path(definition: AppDefinition, entity: str, path: str) -> FieldTarget:
    """Return the field or relation at the end of a field path.

    Raise FieldPathError if the entity, a relation, or the field does not exist.
    """
    current = _entity(definition, entity)
    segments = path.split(".")
    for segment in segments[:-1]:
        relation = current.relations.get(segment)
        if relation is None:
            raise FieldPathError(f"The entity '{entity}' has no relation '{segment}'.")
        if relation.kind not in SINGLE_KINDS:
            raise FieldPathError(
                f"The relation '{entity}.{segment}' is {relation.kind}. A field path can "
                "only go through many_to_one and one_to_one relations."
            )
        entity = relation.target
        current = _entity(definition, entity)
    last = segments[-1]
    if last == "id":
        return FieldTarget(entity, last, None)
    member = current.fields.get(last) or current.relations.get(last)
    if member is None:
        raise FieldPathError(f"The entity '{entity}' has no field or relation '{last}'.")
    return FieldTarget(entity, last, member)


def member_names(definition: AppDefinition, entity: str) -> list[str]:
    """Return the names of the fields and relations of an entity, for hints."""
    found = definition.entities.get(entity)
    return [*found.fields, *found.relations] if found else []


def _entity(definition: AppDefinition, name: str) -> Entity:
    found = definition.entities.get(name)
    if found is None:
        raise FieldPathError(f"The entity '{name}' does not exist.")
    return found
