"""The lines of a record: the records of a `one_to_many` relation that create and update
operations write with the record, in one transaction (ADR 0035).

The target slice has the schema of an item of the lines (`<Entity><Relation>Item`).
The repository of the record has the function that writes the lines, and the
repository of the target has `change` and `remove`, the update and the delete
without a commit. The module of the operation has its input schema: the input
of the record with the lines.
"""

from dataclasses import dataclass
from typing import TYPE_CHECKING

from appgen.bindings.fastapi.pysource import call
from appgen.dsl.model import AppDefinition
from appgen.gen.naming import pascal

if TYPE_CHECKING:
    from appgen.bindings.fastapi.model import PyEntity, PyOperation, PyRelation


@dataclass(slots=True)
class PyLines:
    """The lines of a `one_to_many` relation of an entity."""

    entity: PyEntity
    """The entity of the record."""
    relation: PyRelation
    """The `one_to_many` relation of the record."""
    target: PyEntity
    """The entity of the lines."""
    link: PyRelation
    """The `many_to_one` relation of the lines to the record (the inverse)."""

    @property
    def id(self) -> str:
        return self.relation.id

    @property
    def name(self) -> str:
        """The name of the relation, and the key of the lines in the input."""
        return self.relation.name

    @property
    def attr(self) -> str:
        """The attribute of the lines in the input schema of an operation."""
        return self.relation.attr

    @property
    def item_class(self) -> str:
        """The schema of an item of the lines, in the target slice."""
        return f"{self.entity.name}{pascal(self.relation.name)}Item"

    @property
    def function(self) -> str:
        """The function of the repository of the record that writes the lines."""
        return f"write_{self.relation.name}"

    @property
    def link_attr(self) -> str:
        """The foreign key attribute of the lines that refers to the record."""
        assert self.link.fk_attr is not None
        return self.link.fk_attr

    @property
    def item_relations(self) -> list[PyRelation]:
        """The relations in the item: the input relations of the target, without the link."""
        return [r for r in self.target.input_relations if r.name != self.link.name]

    def declaration(self, kind: str) -> str:
        """Return the declaration of the lines in the input schema of an operation.

        A create takes a list (the default is no lines). An update takes a list
        or nothing: without the key, the lines stay. The schema of the record
        leaves the lines out of its dump, so that the repository does not set
        them on the record.
        """
        list_type = f"list[{self.item_class}]"
        if kind == "create":
            args = [f"default_factory={list_type}", "exclude=True"]
            description = f"The new records of `{self.name}`."
            head = f"{self.attr}: {list_type} = "
        else:
            args = ["default=None", "exclude=True"]
            description = f"All records of `{self.name}`. Without the key, the records stay."
            head = f"{self.attr}: {list_type} | None = "
        if self.attr != self.name:
            args.append(f'alias="{self.name}"')
        return call(head, "Field", [*args, f'description="{description}"'], 4)


def python_lines(
    definition: AppDefinition,
    entities: dict[str, PyEntity],
    operations: dict[str, PyOperation],
) -> None:
    """Give the operations, the entities of the records, and the entities of the lines
    their lines."""
    for name, operation in definition.operations.items():
        entity = entities[operation.entity]
        for relation_name in operation.lines:
            lines = next((ln for ln in entity.lines if ln.name == relation_name), None)
            if lines is None:
                relation = next(r for r in entity.relations if r.name == relation_name)
                target = entities[relation.target]
                link = next(r for r in target.relations if r.name == relation.back_populates)
                lines = PyLines(entity=entity, relation=relation, target=target, link=link)
                entity.lines.append(lines)
                target.line_items.append(lines)
            operations[name].lines.append(lines)
