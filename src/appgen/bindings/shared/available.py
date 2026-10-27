"""The available filters of the views, for the front ends (ADR 0047).

An `available` filter keeps the records without a related record whose
range overlaps the picked days. The range of a related record comes from
the start and the end of a `no_overlap` rule of its entity, for example
the check-in and the check-out of a booking.

The Next.js app and the React app with mock data filter in the browser:
the data access of the entity of the view gives the ranges of the related
records of each rule (`<entity>Ranges`), and the view keeps the records
without a range in the picked days. The ranges come from all related
records, also from the records that a record rule of the related entity
hides, because a record is not free when another user has a booking. The
React app with the FastAPI app sends the days to the list endpoint
instead (`<relation>_free_from` and `<relation>_free_to`).
"""

from dataclasses import dataclass, field

from appgen.dsl.model import AppDefinition
from appgen.dsl.rules import EntityOverlapRule
from appgen.dsl.ui.views import AvailableFilter, CardsView, MapView, TableView
from appgen.gen.naming import camel


@dataclass(slots=True)
class AvailableRule:
    """A relation and a `no_overlap` rule of the available filters of an entity."""

    key: str
    """The relation and the rule, for example `bookings.no_double_booking`."""
    relation: str
    relation_id: str
    target: str
    """The entity of the related records."""
    inverse: str | None
    """For a `one_to_many` relation: the `many_to_one` relation of the related records."""
    many_to_many: bool
    start: str
    end: str
    """The fields of the start and of the end of the range of a related record."""
    dates: bool
    """True for date fields, False for date-time fields."""
    rule_id: str
    ids: list[str] = field(default_factory=list[str])
    """The available filters of the rule, for the traces."""

    @property
    def link(self) -> str:
        """For a `one_to_many` relation: the key of the ID of the record in the related records."""
        return f"{camel(self.inverse or '')}Id"

    @property
    def lookup(self) -> str:
        """The key of the ranges in the lookups of a view, for example `bookingsNoDoubleBooking`."""
        return camel(self.key.replace(".", "_"))


def available_rules(definition: AppDefinition) -> dict[str, list[AvailableRule]]:
    """Return the rules of the available filters of each entity, in the order of the views."""
    found: dict[str, dict[str, AvailableRule]] = {}
    if definition.ui is None:
        return {}
    for view in definition.ui.views.values():
        if not isinstance(view, TableView | CardsView | MapView):
            continue
        for filter_ in view.filters.values():
            if not isinstance(filter_, AvailableFilter):
                continue
            rules = found.setdefault(view.entity, {})
            if filter_.rule not in rules:
                relation = definition.entities[view.entity].relations[filter_.relation]
                target = definition.entities[relation.target]
                rule = target.rules[filter_.rule_name]
                assert isinstance(rule, EntityOverlapRule)
                rules[filter_.rule] = AvailableRule(
                    key=filter_.rule,
                    relation=filter_.relation,
                    relation_id=relation.id,
                    target=relation.target,
                    inverse=relation.inverse if relation.kind == "one_to_many" else None,
                    many_to_many=relation.kind == "many_to_many",
                    start=rule.start,
                    end=rule.end,
                    dates=target.fields[rule.start].type == "date",
                    rule_id=rule.id,
                )
            rules[filter_.rule].ids.append(filter_.id)
    return {entity: list(rules.values()) for entity, rules in found.items()}


def has_available(definition: AppDefinition) -> bool:
    """Return True if a view has an available filter: `@/shared/api` has `OwnerRange`."""
    return bool(available_rules(definition))
