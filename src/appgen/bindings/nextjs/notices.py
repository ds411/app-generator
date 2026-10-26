"""The notices of the Next.js app: the code of the repositories (ADR 0041).

The repository of an entity with a notification calls `<entity>Notify`
after a change: for each notification of the change, it finds the users
at the end of the receiver paths, and adds a notice for each one, with
the values of the text. For each field with mentions (ADR 0043), it adds
a notice for each user that the text mentions for the first time.

The notices of a notification with `email: true` (ADR 0044) wait for the
built-in job `notice_emails`: its route sends their emails with
`src/shared/auth/mail.ts`.
"""

from dataclasses import dataclass, field

from appgen.bindings.nextjs.db import Table
from appgen.bindings.nextjs.jobs import TsJob, TsSchedule
from appgen.bindings.shared.auth import PathStep
from appgen.bindings.shared.notices import (
    NOTICE_EMAILS_BATCH,
    NOTICE_EMAILS_JOB,
    NOTICE_EMAILS_SCHEDULE,
    MentionPlan,
    NoticePlan,
    NoticeReceiver,
    email_notifications,
)
from appgen.bindings.shared.typescript import ts_value
from appgen.dsl.cron import parse_cron
from appgen.dsl.model import AppDefinition
from appgen.gen.naming import camel
from appgen.gen.render import GenerationError


@dataclass(slots=True)
class TsNotice:
    """A notification of an entity, as the TypeScript code of its repository."""

    name: str
    id: str
    """The element ID of the notification."""
    condition: str
    """The condition of the change, of `row` and `before`."""
    users: str
    """The expression of the users: the keys of the row, and the users of the receiver paths."""
    values: list[tuple[str, str]]
    """The values of the text: the name and the expression."""
    element_ids: list[str] = field(default_factory=list[str])
    """The element IDs of the relations of the receiver paths."""


@dataclass(slots=True)
class TsNotify:
    """The function `<entity>Notify` of the repository of an entity."""

    notices: list[TsNotice]
    mentions: list[tuple[str, str]] = field(default_factory=list[tuple[str, str]])
    """The fields with mentions (ADR 0043): the element ID and the call of `addMentions`."""
    paths: dict[str, list[str]] = field(default_factory=dict[str, list[str]])
    """The receiver paths of many steps or of a many-to-many step: the constant and its steps."""
    tables: set[str] = field(default_factory=set[str])
    """The tables to import from `@/shared/db`."""
    helpers: set[str] = field(default_factory=set[str])
    """The names to import from `@/shared/db/notices`."""


TABLE = "notices"
"""The table of the notices, as in the FastAPI app."""
TABLE_CONST = "noticesTable"
TABLE_MODULE = "notices"
SETTINGS_TABLE = "notice_settings"
"""The table of the settings of the emails (ADR 0044), in the module of the notices."""
SETTINGS_CONST = "noticeSettingsTable"


@dataclass(frozen=True, slots=True)
class TsNoticeEmails:
    """The emails of the notices (ADR 0044): the built-in job that sends them."""

    job: TsJob
    ids: list[str]
    """The element IDs of the notifications with `email: true`, for the traces."""
    batch: int = NOTICE_EMAILS_BATCH


def check_notice_table(tables: dict[str, Table], emails: bool = False) -> None:
    """Raise GenerationError if a table of the app has the name or the module of the notices,
    or with `emails` the name of the table of the settings of the emails."""
    for table in tables.values():
        names = {table.name, *(j.name for j in table.join_tables)}
        if TABLE in names or table.const == TABLE_CONST or table.module == TABLE_MODULE:
            raise GenerationError(
                f"The entity '{table.entity}' has the table '{TABLE}', or its module, and the "
                "notices need it. Give the entity another name or table."
            )
        if emails and (SETTINGS_TABLE in names or table.const == SETTINGS_CONST):
            raise GenerationError(
                f"The entity '{table.entity}' has the table '{SETTINGS_TABLE}', and the emails "
                "of the notices need it. Give the entity another name or table."
            )


def ts_notice_emails(definition: AppDefinition) -> TsNoticeEmails | None:
    """Return the built-in job of the emails of the notices, or None without such emails.

    Raise GenerationError if a job of the definition has the name of the built-in job.
    """
    emails = email_notifications(definition)
    if not emails:
        return None
    if NOTICE_EMAILS_JOB in definition.jobs:
        raise GenerationError(
            f"The job '{NOTICE_EMAILS_JOB}' has the name of the built-in job of the emails of "
            "the notices (ADR 0044). Give the job another name."
        )
    job = TsJob(
        name=NOTICE_EMAILS_JOB,
        id=emails[0].id,
        description="Send the emails of the notices of the notifications with `email: true`.",
        schedule=TsSchedule(parse_cron(NOTICE_EMAILS_SCHEDULE)),
        builtin=True,
    )
    return TsNoticeEmails(job, [e.id for e in emails])


def ts_notify(
    plans: list[NoticePlan], tables: dict[str, Table], mentions: list[MentionPlan] | None = None
) -> TsNotify | None:
    """Return the notices of an entity as TypeScript code, or None without notifications and
    mentions."""
    if not plans and not mentions:
        return None
    result = TsNotify(notices=[], helpers={"addNotices"} if plans else set[str]())
    for mention in mentions or []:
        result.helpers.add("addMentions")
        label = "id"
        if mention.label is not None:
            result.helpers.add("textValue")
            label = f"textValue(row.{mention.label})"
        call = (
            f"await addMentions(tx, {ts_value(mention.entity)}, id, {label}, "
            f"row.{mention.key}, before?.{mention.key})"
        )
        result.mentions.append((mention.id, call))
    for plan in plans:
        notice = TsNotice(
            name=plan.name,
            id=plan.id,
            condition=_condition(plan, result),
            users=_users(plan.receivers, tables, result),
            values=[],
        )
        notice.element_ids = [s.element_id for r in plan.receivers for s in r.steps]
        for value in plan.values:
            if value.target is None or value.label is None:
                # A field, or a relation to a record without a display field: its ID.
                result.helpers.add("textValue")
                notice.values.append((value.name, f"textValue(row.{value.key})"))
                continue
            target = tables[value.target].const
            result.tables.add(target)
            result.helpers.add("recordText")
            label = f"{target}.{value.label}"
            code = f"await recordText(tx, {target}, {target}.id, {label}, row.{value.key})"
            notice.values.append((value.name, code))
        result.notices.append(notice)
    return result


def _condition(plan: NoticePlan, result: TsNotify) -> str:
    if plan.kind == "created":
        return "before === undefined"
    if plan.kind == "changed":
        result.helpers.add("changed")
        return f"changed(row, before, {ts_value(list(plan.keys))})"
    after = ts_value(plan.after)
    if len(plan.before) == 1:
        return (
            f"before !== undefined && row.{plan.state} === {after} && "
            f"before.{plan.state} === {ts_value(plan.before[0])}"
        )
    return (
        f"before !== undefined && row.{plan.state} === {after} && "
        f"{ts_value(list(plan.before))}.includes(String(before.{plan.state}))"
    )


def _users(
    receivers: tuple[NoticeReceiver, ...], tables: dict[str, Table], result: TsNotify
) -> str:
    """Return the expression of the users: a foreign key of the row, or the users of a path."""
    items: list[str] = []
    for receiver in receivers:
        first = receiver.steps[0]
        if len(receiver.steps) == 1 and not first.many:
            items.append(f"row.{first.key}")
            continue
        const = camel(receiver.path.replace(".", "_")) + "Path"
        if const not in result.paths:
            result.paths[const] = [_step(step, tables, result) for step in receiver.steps]
        result.helpers.update(("pathUsers", "type PathStep"))
        items.append(f"...(await pathUsers(tx, id, {const}))")
    if len(items) == 1 and items[0].startswith("..."):
        return items[0].removeprefix("...(").removesuffix(")")
    return f"[{', '.join(items)}]"


def _step(step: PathStep, tables: dict[str, Table], result: TsNotify) -> str:
    """Return a step of a receiver path: the table, the column of the IDs, and the next column."""
    table = tables[step.entity]
    if step.many:
        item = next(i for i in table.lists if i.element_id == step.element_id)
        result.tables.add(item.join_const)
        join = item.join_const
        return f"[{join}, {join}.{item.owner_key}, {join}.{item.target_key}]"
    result.tables.add(table.const)
    return f"[{table.const}, {table.const}.id, {table.const}.{step.key}]"
