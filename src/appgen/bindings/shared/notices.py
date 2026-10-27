"""The notices of the front ends (React and Next.js): the shared plan (ADR 0041).

A notification of the definition gives each user at the end of its
receiver paths a notice when a record changes. The Next.js app keeps the
notices in the table `notices`, as the FastAPI app does, and its
repositories add them. The React app keeps them in its mock store, or
reads them from the FastAPI app. The bell of the top bar shows the
notices of the signed-in user: a shared template.

The front ends write the text of a notice from the name of the
notification and the values of the record: the text is a key of the
translations, and the values go into the translation.

A `text` field with `mentions: true` (ADR 0043) gives a notice to each
user that a new or a changed text mentions for the first time, with the
built-in notification `@mention`. A mention in the text is
`@[<display value>](<ID of the user>)`.
"""

import json
import re
from dataclasses import dataclass, replace

from appgen.bindings.shared.auth import PathStep, path_steps
from appgen.dsl.model import AppDefinition
from appgen.dsl.notifications import Notification
from appgen.dsl.ui.views import DetailView
from appgen.gen.binding import Output
from appgen.gen.naming import camel

_PARAM = re.compile(r"\{([a-z][a-z0-9_]*)\}")

MENTION = "@mention"
"""The name of the notices of the mentions (ADR 0043). A notification name cannot have `@`."""
MENTION_TEXT = "You are mentioned in {record}."
"""The text of the notices of the mentions: `record` is the display value of the record."""
_UUID = "[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}"
MENTION_PATTERN = rf"@\[([^\[\]\n]+)\]\(({_UUID})\)"
"""A mention in a text: the display value of the user, and its ID."""


@dataclass(frozen=True, slots=True)
class NoticeValue:
    """A value in braces of the text of a notice, in TypeScript terms."""

    name: str
    """The name in braces, for example `room`."""
    key: str
    """The key of the record: `title`, or `roomId` for a relation."""
    target: str | None = None
    """The target entity of a `many_to_one` relation, or None for a field."""
    label: str | None = None
    """The key of the display field of the target, or None: the value is the ID."""


@dataclass(frozen=True, slots=True)
class NoticeReceiver:
    """A receiver path of a notification: the relations from the record to the users."""

    path: str
    """The path in the definition, for example `project.team.members`."""
    steps: tuple[PathStep, ...]


@dataclass(frozen=True, slots=True)
class NoticePlan:
    """A notification in TypeScript terms."""

    name: str
    id: str
    """The element ID of the notification, for the traces."""
    entity: str
    kind: str
    """`created`, `changed`, or `transition`."""
    text: str
    receivers: tuple[NoticeReceiver, ...]
    values: tuple[NoticeValue, ...]
    keys: tuple[str, ...] = ()
    """For `changed`: the keys of the watched fields and relations."""
    state: str | None = None
    """For a transition: the key of the field of the workflow."""
    before: tuple[str, ...] = ()
    """For a transition: the states before the change."""
    after: str | None = None
    """For a transition: the state after the change."""


@dataclass(frozen=True, slots=True)
class MentionPlan:
    """A `text` field with mentions (ADR 0043), in TypeScript terms."""

    entity: str
    name: str
    """The name of the field."""
    key: str
    """The key of the field in the records, for example `notes`."""
    id: str
    """The element ID of the field."""
    label: str | None
    """The key of the stored display field of the entity, or None: the value is the ID."""


def has_notices(definition: AppDefinition) -> bool:
    """Return True if the app shows notices: it has notifications or mentions, and a sign-in."""
    return (
        bool(definition.notifications) or has_mentions(definition)
    ) and definition.auth is not None


def has_mentions(definition: AppDefinition) -> bool:
    """Return True if a field of the app has mentions and the app has a sign-in."""
    return definition.auth is not None and any(
        f.mentions for e in definition.entities.values() for f in e.fields.values()
    )


def mention_plans(definition: AppDefinition, entity: str | None = None) -> list[MentionPlan]:
    """Return the fields with mentions, all or of one entity, in source order (ADR 0043)."""
    if definition.auth is None:
        return []
    plans: list[MentionPlan] = []
    for entity_name, e in definition.entities.items():
        if entity is not None and entity_name != entity:
            continue
        label = e.display_field
        if label is not None:
            field = e.fields.get(label)
            if field is None or field.computed is not None or field.is_file:
                label = None
        for name, f in e.fields.items():
            if f.mentions:
                plans.append(
                    MentionPlan(
                        entity_name, name, camel(name), f.id, camel(label) if label else None
                    )
                )
    return plans


def mention_link(definition: AppDefinition) -> tuple[str, str] | None:
    """Return the detail page of the users for the links of the mentions, or None."""
    if definition.auth is None:
        return None
    return _detail_page(definition, definition.auth.user_entity)


def notice_rules() -> tuple[Output, ...]:
    """Return the output rules of the bell of the notices, for the top bars and the bare layout,
    and of the mentions (ADR 0043)."""
    return (
        *(
            Output(
                template=f"ui/features/notices/{template}.j2",
                path=f"src/features/notices/{path}",
                when="has_notices(definition)",
            )
            for template, path in (
                ("index.ts", "index.ts"),
                ("notice-texts.ts", "model/notice-texts.ts"),
                ("notice-bell.tsx", "ui/notice-bell.tsx"),
            )
        ),
        Output(
            template="ui/features/notices/mentions.ts.j2",
            path="src/shared/lib/mentions.ts",
            when="has_mentions(definition)",
        ),
    )


def notice_plans(definition: AppDefinition, entity: str | None = None) -> list[NoticePlan]:
    """Return the notifications in TypeScript terms, all or of one entity, in source order."""
    if not has_notices(definition):
        return []
    return [
        _plan(definition, name, notification)
        for name, notification in definition.notifications.items()
        if entity is None or notification.entity == entity
    ]


def notice_summary(notification: Notification) -> str:
    """Return the change that gives the notices of a notification, for the README."""
    if notification.event == "created":
        return f"A new {notification.entity}"
    if notification.event == "changed":
        fields = ", ".join(f"`{name}`" for name in notification.fields or [])
        if fields:
            return f"A change of {fields} of a {notification.entity}"
        return f"A change of a {notification.entity}"
    return f"The transition `{notification.transition}`"


def notice_texts(definition: AppDefinition) -> dict[str, str]:
    """Return the text of each notification, by name, and the text of the mentions."""
    if not has_notices(definition):
        return {}
    texts = {name: n.text for name, n in definition.notifications.items()}
    if has_mentions(definition):
        texts[MENTION] = MENTION_TEXT
    return texts


def notice_ids(definition: AppDefinition) -> list[str]:
    """Return the element IDs of the notifications and of the fields with mentions."""
    if not has_notices(definition):
        return []
    ids = [n.id for n in definition.notifications.values()]
    return ids + [m.id for m in mention_plans(definition)]


def notice_links(definition: AppDefinition) -> dict[str, tuple[str, str]]:
    """Return the detail page of each entity of a notice: the page name and its parameter.

    The entities are those of the notifications and of the fields with
    mentions. The page shows a detail view of the entity, and has one
    parameter, the ID of the record: `/bookings/{id}` gives the parameter
    `id`. An entity without such a page has no link: its notices show only
    their text.
    """
    if not has_notices(definition) or definition.ui is None:
        return {}
    entities = [n.entity for n in definition.notifications.values()]
    entities += [m.entity for m in mention_plans(definition)]
    links: dict[str, tuple[str, str]] = {}
    for entity in dict.fromkeys(entities):
        link = _detail_page(definition, entity)
        if link is not None:
            links[entity] = link
    return links


def _detail_page(definition: AppDefinition, entity: str) -> tuple[str, str] | None:
    """Return the first page with a detail view of an entity and one parameter, or None."""
    if definition.ui is None:
        return None
    for page_name, page in definition.pages.items():
        view_name = page.content.view if page.content is not None else None
        view = definition.ui.views.get(view_name) if view_name is not None else None
        params = _PARAM.findall(page.path)
        if isinstance(view, DetailView) and view.entity == entity and len(params) == 1:
            return page_name, params[0]
    return None


def _plan(definition: AppDefinition, name: str, notification: Notification) -> NoticePlan:
    entity = definition.entities[notification.entity]
    values: list[NoticeValue] = []
    for value in notification.values():
        if value in entity.fields:
            values.append(NoticeValue(value, camel(value)))
            continue
        target = definition.entities[entity.relations[value].target]
        label = target.display_field
        stored = label is not None and label in target.fields
        if stored and label is not None:
            field = target.fields[label]
            stored = field.computed is None and not field.is_file
        values.append(
            NoticeValue(
                value,
                camel(value) + "Id",
                entity.relations[value].target,
                camel(label) if stored and label is not None else None,
            )
        )
    receivers = tuple(
        NoticeReceiver(path, path_steps(definition, notification.entity, path))
        for path in notification.receivers
    )
    plan = NoticePlan(
        name=name,
        id=notification.id,
        entity=notification.entity,
        kind=notification.event or "transition",
        text=notification.text,
        receivers=receivers,
        values=tuple(values),
    )
    if notification.event == "changed":
        watched = notification.fields or [
            *(n for n, f in entity.fields.items() if f.computed is None and not f.is_file),
            *(n for n, r in entity.relations.items() if r.kind == "many_to_one"),
        ]
        keys = tuple(camel(m) if m in entity.fields else camel(m) + "Id" for m in watched)
        return replace(plan, keys=keys)
    parts = notification.transition_parts()
    if parts is None:
        return plan
    workflow_name, transition_name = parts
    workflow = next(
        w
        for n, w in definition.workflows.items()
        if w.entity == notification.entity
        and transition_name in w.transitions
        and workflow_name in (None, n)
    )
    transition = workflow.transitions[transition_name]
    return replace(
        plan, state=camel(workflow.field), before=tuple(transition.from_), after=transition.to
    )


@dataclass(frozen=True, slots=True)
class MockNotice:
    """A notification as the code of the mock store of the React app."""

    name: str
    id: str
    condition: str
    """The condition of the change, of `record` and `before`."""
    users: str
    """The expression of the users."""
    values: tuple[tuple[str, str], ...]
    """The values of the text: the name and the expression."""
    element_ids: tuple[str, ...]
    """The element IDs of the relations of the receiver paths."""


@dataclass(frozen=True, slots=True)
class MockNotify:
    """The notices of the changes of an entity in the mock store of the React app."""

    notices: tuple[MockNotice, ...]
    mentions: tuple[tuple[str, str], ...]
    """The fields with mentions (ADR 0043): the element ID and the call of `addMentions`."""
    helpers: tuple[str, ...]
    """The names to import from `@/shared/api/notices`."""
    store: tuple[str, ...]
    """The names to import from `@/shared/api`: `pathIds` and `recordValue`."""


def mock_notify(
    plans: list[NoticePlan], mentions: list[MentionPlan] | None = None, users: str = ""
) -> MockNotify | None:
    """Return the notifications and the mentions of an entity as the code of the mock store,
    or None (ADR 0041, ADR 0043). `users` is the user entity."""
    if not plans and not mentions:
        return None
    notices = tuple(
        MockNotice(
            name=plan.name,
            id=plan.id,
            condition=_mock_condition(plan),
            users=_mock_users(plan.receivers),
            values=tuple((value.name, _mock_value(value)) for value in plan.values),
            element_ids=tuple(
                dict.fromkeys(step.element_id for r in plan.receivers for step in r.steps)
            ),
        )
        for plan in plans
    )
    calls = tuple(
        (
            m.id,
            f"addMentions({_js(m.entity)}, record.id, "
            f"{f'textValue(record.{m.label})' if m.label else 'record.id'}, "
            f"record.{m.key}, before?.{m.key}, {_js(users)})",
        )
        for m in mentions or []
    )
    code = " ".join(f"{n.condition} {n.users} {' '.join(c for _, c in n.values)}" for n in notices)
    code += " ".join(c for _, c in calls)
    helpers = (
        *(("addMentions",) if calls else ()),
        *(("addNotices",) if notices else ()),
        *(name for name in ("changed", "textValue") if f"{name}(" in code),
    )
    return MockNotify(
        notices=notices,
        mentions=calls,
        helpers=helpers,
        store=tuple(name for name in ("pathIds", "recordValue") if f"{name}(" in code),
    )


def _mock_condition(plan: NoticePlan) -> str:
    if plan.kind == "created":
        return "before === undefined"
    if plan.kind == "changed":
        return f"changed(record, before, {_js(list(plan.keys))})"
    state, after = plan.state, _js(plan.after)
    if len(plan.before) == 1:
        return (
            f"before !== undefined && record.{state} === {after} && "
            f"before.{state} === {_js(plan.before[0])}"
        )
    return (
        f"before !== undefined && record.{state} === {after} && "
        f"{_js(list(plan.before))}.includes(String(before.{state}))"
    )


def _mock_users(receivers: tuple[NoticeReceiver, ...]) -> str:
    items: list[str] = []
    for receiver in receivers:
        first = receiver.steps[0]
        if len(receiver.steps) == 1 and not first.many:
            items.append(f"record.{first.key}")
            continue
        steps = ", ".join(
            f"{{ key: {_js(s.key)}, target: {_js(s.target)} }}" for s in receiver.steps
        )
        items.append(f"...pathIds(record, [{steps}])")
    if len(items) == 1 and items[0].startswith("..."):
        return items[0].removeprefix("...")
    return f"[{', '.join(items)}]"


def _mock_value(value: NoticeValue) -> str:
    if value.target is None or value.label is None:
        return f"textValue(record.{value.key})"
    return f"textValue(recordValue({_js(value.target)}, record.{value.key}, {_js(value.label)}))"


def _js(value: object) -> str:
    return json.dumps(value, ensure_ascii=False)
