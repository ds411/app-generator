"""The operations with lines in the front ends (ADR 0035).

A `create` or an `update` operation with `lines` writes a record and the
records of its `one_to_many` relations in one request, for example an
invoice and its lines. Each front end gives such an operation a feature
slice `src/features/<operation>` with the function of the operation, and
each relation of lines an item type in the slice of the related entity,
for example `InvoiceLinesItem`: the input of a line, without the relation
to the record, and with an optional ID.
"""

from dataclasses import dataclass

from appgen.dsl.model import AppDefinition
from appgen.gen.naming import camel, pascal


@dataclass(frozen=True, slots=True)
class LineItem:
    """A relation of lines: the item of a line in the input of an operation."""

    owner: str
    """The entity of the record, for example `Invoice`."""
    relation: str
    """The `one_to_many` relation of the record, for example `lines`."""
    target: str
    """The entity of the lines, for example `InvoiceLine`."""
    link: str
    """The key of the relation to the record in a line, for example `invoiceId`."""
    element_id: str
    """The element ID of the relation."""

    @property
    def type(self) -> str:
        """Return the TypeScript type of an item, for example `InvoiceLinesItem`."""
        return f"{pascal(self.owner)}{pascal(self.relation)}Item"

    @property
    def schema(self) -> str:
        """Return the zod schema of an item, for example `invoiceLinesItemSchema`."""
        return f"{camel(self.type)}Schema"

    @property
    def key(self) -> str:
        """Return the key of the items in the lines of an operation, for example `lines`."""
        return camel(self.relation)

    @property
    def list_function(self) -> str:
        """Return the function of the slice of the lines that lists the lines of a record."""
        return f"list{pascal(self.relation)}Of{pascal(self.owner)}"


@dataclass(frozen=True, slots=True)
class LinesOperation:
    """A `create` or an `update` operation with lines."""

    name: str
    kind: str
    entity: str
    element_id: str
    items: list[LineItem]

    @property
    def type(self) -> str:
        """Return the TypeScript type of the lines of the operation: `CreateInvoiceLines`."""
        return f"{pascal(self.name)}Lines"

    @property
    def targets(self) -> list[str]:
        """Return the entities of the lines, without duplicates."""
        return list(dict.fromkeys(item.target for item in self.items))


def line_item(definition: AppDefinition, entity: str, relation_name: str) -> LineItem:
    """Return the item of a `one_to_many` relation of lines."""
    relation = definition.entities[entity].relations[relation_name]
    assert relation.inverse is not None
    return LineItem(
        owner=entity,
        relation=relation_name,
        target=relation.target,
        link=f"{camel(relation.inverse)}Id",
        element_id=relation.id,
    )


def lines_operations(definition: AppDefinition) -> dict[str, LinesOperation]:
    """Return the `create` and the `update` operations with lines, by name."""
    return {
        name: LinesOperation(
            name=name,
            kind=operation.kind,
            entity=operation.entity,
            element_id=operation.id,
            items=[line_item(definition, operation.entity, item) for item in operation.lines],
        )
        for name, operation in definition.operations.items()
        if operation.lines and operation.kind in ("create", "update")
    }


def line_items(definition: AppDefinition, entity: str) -> list[LineItem]:
    """Return the relations of lines whose lines are records of an entity."""
    items = {
        (item.owner, item.relation): item
        for operation in lines_operations(definition).values()
        for item in operation.items
        if item.target == entity
    }
    return [items[key] for key in sorted(items)]
