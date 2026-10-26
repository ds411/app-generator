"""The jobs: the cron expressions, the offsets, the checks, the FastAPI worker, and the
Next.js routes (ADR 0029)."""

import datetime as dt
from pathlib import Path
from textwrap import dedent

import pytest
import yaml

from appgen.bindings import fastapi, nextjs
from appgen.dsl import load_definition, load_definition_text, validate_definition
from appgen.dsl.cron import CronError, parse_cron
from appgen.dsl.jobs import parse_offset
from appgen.gen.generator import generate
from appgen.gen.render import GenerationError

EXAMPLE = Path(__file__).parent.parent / "examples" / "room-booking" / "app.yaml"

BASE = dedent(
    """\
    version: 0
    app: { name: tracker, title: Tracker }
    entities:
      Task:
        fields:
          title: { type: string, required: true }
          due_on: { type: date }
          due_at: { type: datetime }
          points: { type: integer }
          status: { type: enum, values: [open, done], default: open }
    operations:
      list_tasks: { kind: list, entity: Task }
      remind:
        kind: custom
        entity: Task
        params:
          note: { type: string }
      escalate:
        kind: custom
        entity: Task
        params:
          level: { type: integer, required: true }
    """
)

JOBS = dedent(
    """\
    jobs:
      reminder:
        entity: Task
        at: due_at
        offset: -2h
        filter: { status: open }
        operation: remind
      cleanup:
        schedule: "*/15 * * * *"
        entity: Task
        filter: { due_on: { lt: $today } }
        operation: remind
      digest:
        description: Send a digest.
        schedule: "@daily"
    """
)

T = dt.UTC


def codes(text: str) -> list[tuple[str, str | None]]:
    definition = load_definition_text(text, "app.yaml")
    return [(d.code, d.element_id) for d in validate_definition(definition)]


def job(text: str) -> str:
    """Return a definition with one job `j`, from the lines of the job."""
    return BASE + "jobs:\n  j:\n" + "".join(f"    {line}\n" for line in dedent(text).splitlines())


def test_a_cron_expression_has_five_fields_names_steps_and_macros() -> None:
    cron = parse_cron("*/15 6-8 1,15 jan-mar mon-fri")
    assert cron.minutes == {0, 15, 30, 45}
    assert cron.hours == {6, 7, 8}
    assert cron.days == {1, 15}
    assert cron.months == {1, 2, 3}
    assert cron.weekdays == {1, 2, 3, 4, 5}
    assert cron.either_day
    assert parse_cron("@weekly").expression == "0 0 * * 0"
    assert parse_cron("0 0 * * 7").weekdays == {0}
    assert parse_cron("5/20 * * * *").minutes == {5, 25, 45}
    assert not parse_cron("0 0 * * 1").either_day


def test_a_cron_day_matches_one_of_the_day_fields_when_both_are_restricted() -> None:
    # The 13th of each month, and each Friday.
    cron = parse_cron("0 12 13 * 5")
    friday = dt.datetime(2026, 6, 19, 12, tzinfo=T)
    the_13th = dt.datetime(2026, 6, 13, 12, tzinfo=T)
    assert cron.matches(friday)
    assert cron.matches(the_13th)
    assert not cron.matches(dt.datetime(2026, 6, 18, 12, tzinfo=T))
    # Only the day of the week is restricted: each Friday.
    assert parse_cron("0 12 * * 5").matches(friday)
    assert not parse_cron("0 12 * * 5").matches(the_13th)


def test_the_next_time_of_a_cron_expression_is_in_utc() -> None:
    cron = parse_cron("0 7 * * 1")
    start = dt.datetime(2026, 6, 15, 9, tzinfo=dt.timezone(dt.timedelta(hours=2)))
    assert cron.next_after(start) == dt.datetime(2026, 6, 22, 7, tzinfo=T)
    assert parse_cron("0 0 31 2 *").next_after(start) is None


@pytest.mark.parametrize(
    ("text", "message"),
    [
        ("* * * *", "has 4"),
        ("60 * * * *", "not in the range 0-59"),
        ("* * * foo *", "'foo' of the month field"),
        ("5-1 * * * *", "ends before it starts"),
        ("*/0 * * * *", "1 or more"),
        ("@often", "not known"),
        ("1;2 * * * *", "not valid"),
    ],
)
def test_a_wrong_cron_expression_tells_why(text: str, message: str) -> None:
    with pytest.raises(CronError, match=message):
        parse_cron(text)


def test_an_offset_is_a_number_with_a_sign_and_a_unit() -> None:
    assert parse_offset("-24h") == dt.timedelta(hours=-24)
    assert parse_offset("4h") == dt.timedelta(hours=4)
    assert parse_offset("+30m") == dt.timedelta(minutes=30)
    assert parse_offset("2w") == dt.timedelta(weeks=2)
    for text in ("24", "1.5h", "-2y", "h"):
        with pytest.raises(ValueError, match="not valid"):
            parse_offset(text)


def test_the_jobs_are_valid_and_have_ids() -> None:
    definition = load_definition_text(BASE + JOBS, "app.yaml")
    assert validate_definition(definition) == []
    assert definition.jobs["reminder"].offset_delta() == dt.timedelta(hours=-2)
    assert definition.find("jobs.digest") is not None


def test_a_job_has_a_schedule_or_a_time() -> None:
    both = job("""
        schedule: "0 * * * *"
        entity: Task
        at: due_at
        operation: remind
        """)
    assert codes(both) == [("invalid-option", "jobs.j")]
    assert codes(job("description: Never.")) == [("missing-key", "jobs.j")]
    assert codes(job('schedule: "0 25 * * *"')) == [("invalid-value", "jobs.j")]
    offset = job("""
        schedule: "0 * * * *"
        offset: -1h
        """)
    assert codes(offset) == [("invalid-option", "jobs.j")]
    unit = job("""
        entity: Task
        at: due_at
        offset: -1y
        operation: remind
        """)
    assert codes(unit) == [("invalid-value", "jobs.j")]


def test_the_field_of_at_is_a_stored_date() -> None:
    def at(field: str) -> str:
        return job(f"""
            entity: Task
            at: {field}
            operation: remind
            """)

    assert codes(at("due_on")) == []
    assert codes(at("points")) == [("unsuitable-field", "jobs.j")]
    assert codes(at("due")) == [("unknown-reference", "jobs.j")]


def test_a_job_runs_a_custom_operation_of_its_entity() -> None:
    def operation(name: str) -> str:
        return job(f"""
            schedule: "@hourly"
            entity: Task
            operation: {name}
            """)

    assert codes(operation("list_tasks")) == [("unsuitable-operation", "jobs.j")]
    # A required param without a default: the job cannot give a value.
    assert codes(operation("escalate")) == [("unsuitable-operation", "jobs.j")]
    assert codes(operation("remnd")) == [("unknown-reference", "jobs.j")]
    other = BASE.replace(
        "operations:\n",
        "  Note:\n    fields:\n      text: { type: string }\noperations:\n"
        "  pin: { kind: custom, entity: Note }\n",
    )
    text = other + "jobs:\n  j: { schedule: '@hourly', entity: Task, operation: pin }\n"
    assert codes(text) == [("unsuitable-operation", "jobs.j")]
    assert codes(job('schedule: "@hourly"\nentity: Task')) == [("missing-key", "jobs.j")]


def test_a_job_without_an_entity_has_no_records() -> None:
    assert codes(job('schedule: "@hourly"\noperation: remind')) == [("missing-key", "jobs.j")]
    assert codes(job("at: due_at")) == [("missing-key", "jobs.j")]
    text = job('schedule: "@hourly"\nfilter: { status: open }')
    assert codes(text) == [("invalid-option", "jobs.j")]


def test_the_filter_of_a_job_has_the_checks_of_the_dashboards() -> None:
    text = job("""
        schedule: "@hourly"
        entity: Task
        filter: { state: open }
        operation: remind
        """)
    assert [code for code, _ in codes(text)] == ["unknown-reference"]


def files_of(text: str) -> dict[str, str]:
    definition = load_definition_text(text, "app.yaml")
    return {f.path: f.content for f in generate(definition, fastapi.BINDING).files}


def test_the_fastapi_app_has_a_module_and_a_test_for_each_job() -> None:
    files = files_of(BASE + JOBS)
    for name in ("reminder", "cleanup", "digest"):
        assert f"# @trace jobs.{name} file" in files[f"app/jobs/{name}.py"]
        assert f"tests/jobs/test_{name}.py" in files
        assert f'    "{name}": {name}.run,' in files["app/worker.py"]
    assert "app/jobs/digest_ext.py" in files
    assert "app/jobs/reminder_ext.py" not in files
    reminder = files["app/jobs/reminder.py"]
    assert "OFFSET = dt.timedelta(hours=-2)" in reminder
    assert "statement = statement.where(Task.status == TaskStatus.OPEN)" in reminder
    assert "await remind_ext.remind(session, record, RemindParams())" in reminder
    cleanup = files["app/jobs/cleanup.py"]
    assert "minutes=frozenset({0, 15, 30, 45})," in cleanup
    assert "day = moment.date()" in cleanup
    assert "statement = statement.where(Task.due_on < day)" in cleanup
    assert (
        '    sa.PrimaryKeyConstraint("key", name="pk_job_runs"),'
        in files["migrations/versions/0001_schema.py"]
    )
    assert "    jobs_window_minutes: int = 60\n" in files["app/core/config.py"]
    assert "  worker:\n" in files["compose.yaml"]


def test_the_fastapi_app_without_jobs_has_no_worker() -> None:
    files = files_of(BASE)
    assert not [path for path in files if "jobs" in path or "worker" in path]
    assert "job_runs" not in files["migrations/versions/0001_schema.py"]
    assert "JobRun" not in files["app/models.py"]


def test_the_room_booking_example_sends_a_reminder_a_day_before_each_booking() -> None:
    definition = load_definition(EXAMPLE)
    result = generate(definition, fastapi.BINDING)
    files = {f.path: f.content for f in result.files}
    reminder = files["app/jobs/booking_reminder.py"]
    assert "OFFSET = dt.timedelta(hours=-24)" in reminder
    assert "await remind_organizer_ext.remind_organizer(session, record)" in reminder
    assert "# @trace:gap jobs.weekly_report file" in files["app/jobs/weekly_report_ext.py"]
    assert "app/jobs/expire_requests_ext.py" not in files


def test_a_job_cannot_have_the_name_of_a_module_or_a_table() -> None:
    text = BASE + JOBS + "  digest_ext:\n    schedule: '@daily'\n"
    with pytest.raises(GenerationError, match="name of a module"):
        files_of(text)
    table = BASE.replace("  Task:\n", "  Task:\n    x-fastapi-table: job_runs\n")
    with pytest.raises(GenerationError, match="job_runs"):
        files_of(table + JOBS)


def nextjs_files(text: str) -> dict[str, str]:
    definition = load_definition_text(text, "app.yaml")
    return {f.path: f.content for f in generate(definition, nextjs.BINDING).files}


def test_the_nextjs_app_has_a_module_and_a_route_for_each_job() -> None:
    files = nextjs_files(BASE + JOBS)
    for name, module in (("reminder", "reminder"), ("cleanup", "cleanup"), ("digest", "digest")):
        assert f"// @trace jobs.{name} file" in files[f"src/app/jobs/{module}.ts"]
        route = files[f"app/api/jobs/{name}/route.ts"]
        assert f'return handleJob(request, "{name}", run{name.title()});' in route
    assert "src/app/jobs/digest.ext.ts" in files
    assert "src/app/jobs/reminder.ext.ts" not in files
    reminder = files["src/app/jobs/reminder.ts"]
    assert "const OFFSET_MS = -7_200_000;" in reminder
    assert 'return eq(taskTable.status, "open");' in reminder
    assert "await remind(record, remindParamsSchema.parse({}));" in reminder
    # The field `due_at` is not required: the runs leave out the records without a value.
    assert "row.value === null ? [] :" in reminder
    cleanup = files["src/app/jobs/cleanup.ts"]
    assert "  minutes: [0, 15, 30, 45]," in cleanup
    assert "const today = dateOf(now);" in cleanup
    assert "return lt(taskTable.dueOn, today);" in cleanup
    assert 'export * from "./job-runs";' in files["src/shared/db/schema/index.ts"]
    assert 'pgTable("job_runs", {' in files["src/shared/db/schema/job-runs.ts"]
    assert "export async function inTransaction<T>(" in files["src/shared/db/client.ts"]
    assert "  jobs:\n" in files["compose.yaml"]
    assert "JOBS_SECRET=" in files["deploy/kubernetes/secret.example.env"]
    assert "  - jobs.yaml\n" in files["deploy/kubernetes/kustomization.yaml"]


def test_the_nextjs_app_calls_the_routes_with_cron_jobs() -> None:
    files = nextjs_files(BASE + JOBS)
    documents = [d for d in yaml.safe_load_all(files["deploy/kubernetes/jobs.yaml"]) if d]
    schedules = {d["metadata"]["name"]: d["spec"]["schedule"] for d in documents}
    # One CronJob for each job with a schedule, and one each minute for the jobs with `at`.
    assert schedules == {
        "tracker-web-cleanup": "*/15 * * * *",
        "tracker-web-digest": "0 0 * * *",
        "tracker-web-each-minute": "* * * * *",
    }
    container = documents[2]["spec"]["jobTemplate"]["spec"]["template"]["spec"]["containers"][0]
    assert "for job in reminder; do" in container["args"][0]
    assert '"http://tracker-web/api/jobs/$job"' in container["args"][0]
    assert container["env"][0]["valueFrom"]["secretKeyRef"]["key"] == "JOBS_SECRET"


def test_the_nextjs_app_without_jobs_has_no_routes_of_jobs() -> None:
    files = nextjs_files(BASE)
    assert not [path for path in files if "jobs" in path or "job-runs" in path]
    assert "AsyncLocalStorage" not in files["src/shared/db/client.ts"]
    assert "JOBS_" not in files["compose.yaml"] + files[".env.example"]


def test_the_name_of_a_cron_job_fits_in_kubernetes() -> None:
    long = BASE.replace("name: tracker", "name: a-tracker-with-a-very-long-name")
    text = long + "jobs:\n  a_job_with_a_long_name_too: { schedule: '@daily' }\n"
    files = nextjs_files(text)
    names = [
        d["metadata"]["name"] for d in yaml.safe_load_all(files["deploy/kubernetes/jobs.yaml"]) if d
    ]
    assert len(names) == 1 and len(names[0]) <= 52
    assert names[0].startswith("a-tracker-with-a-very-long-name-web-a-job")


def test_the_nextjs_room_booking_app_sends_a_reminder_a_day_before_each_booking() -> None:
    files = {f.path: f.content for f in generate(load_definition(EXAMPLE), nextjs.BINDING).files}
    reminder = files["src/app/jobs/booking-reminder.ts"]
    assert "const OFFSET_MS = -86_400_000;" in reminder
    assert "await remindOrganizer(record);" in reminder
    assert "// @trace:gap jobs.weekly_report file" in files["src/app/jobs/weekly-report.ext.ts"]
    assert "src/app/jobs/expire-requests.ext.ts" not in files


def test_a_nextjs_table_cannot_have_the_name_of_the_table_of_the_runs() -> None:
    # The entity JobRuns has the table `job_runs` and the const `jobRunsTable`.
    text = (BASE + JOBS).replace("Task", "JobRuns")
    with pytest.raises(GenerationError, match="job_runs"):
        nextjs_files(text)
