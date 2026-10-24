import re
from pathlib import Path

from appgen.bindings import react
from appgen.bindings.react.api_client import api_entities, data_source
from appgen.dsl import load_definition_text, validate_definition
from appgen.gen.extensions import check_extensions
from appgen.gen.generator import generate

ROOT = Path(__file__).parent.parent
EXAMPLE = ROOT / "examples" / "project-tracker" / "app.yaml"


def definition_text(example: str, data: str | None) -> str:
    text = (ROOT / "examples" / example / "app.yaml").read_text()
    if data is None:
        return text
    return re.sub(r"(?m)^app:\n", f"app:\n  x-react-data: {data}\n", text, count=1)


def files(example: str, data: str | None) -> dict[str, str]:
    definition = load_definition_text(
        definition_text(example, data), str(ROOT / "examples" / example / "app.yaml")
    )
    return {f.path: f.content for f in generate(definition, react.BINDING).files}


def test_without_the_key_the_app_uses_mock_data() -> None:
    output = files("project-tracker", None)
    assert "src/shared/api/mock-store.ts" in output
    assert "src/shared/api/http.ts" not in output
    assert (
        "new MockStore<Project, ProjectInput>(" in output["src/entities/project/api/project-api.ts"]
    )


def test_with_the_key_the_app_uses_the_api_client() -> None:
    output = files("project-tracker", "api")
    assert "src/shared/api/mock-store.ts" not in output
    assert "src/entities/project/api/project-mock-data.ts" not in output
    assert "src/shared/api/http-store.ts" in output
    api = output["src/entities/project/api/project-api.ts"]
    assert 'new HttpStore<Project, ProjectInput>("Project", "/projects", {' in api
    assert '"due_date": "dueDate",' in api
    assert '"owner_id": "ownerId",' in api
    assert '"member_ids": "members",' in api
    assert 'numbers: ["budget"],' in api
    assert "VITE_API_URL" in output["src/vite-env.d.ts"]
    assert "ARG VITE_API_URL" in output["Dockerfile"]


def test_the_endpoints_are_the_endpoints_of_the_fastapi_app() -> None:
    definition = load_definition_text(definition_text("project-tracker", "api"), str(EXAMPLE))
    assert data_source(definition) == "api"
    endpoints = {
        (e.operation, e.method, e.path) for e in api_entities(definition)["Project"].endpoints
    }
    assert ("list_projects", "GET", "/projects") in endpoints
    assert ("read_project", "GET", "/projects/{id}") in endpoints
    assert ("update_project", "PATCH", "/projects/{id}") in endpoints


def test_a_custom_operation_calls_its_endpoint_and_has_no_extension_file() -> None:
    output = files("room-booking", "api")
    operation = output["src/features/cancel-booking/api/cancel-booking.gen.ts"]
    assert 'await bookingApi.call("POST", "/cancel-booking", id, {' in operation
    assert '"reason": params.reason,' in operation
    assert not [path for path in output if path.endswith("cancel-booking.ext.ts")]
    auth = output["src/shared/auth/index.ts"]
    assert 'apiRequest("POST", "/auth/sign-in", { username, password })' in auth
    assert "MOCK_PASSWORD" not in auth


def test_the_key_takes_only_mock_or_api() -> None:
    definition = load_definition_text(definition_text("project-tracker", "rest"), str(EXAMPLE))
    assert validate_definition(definition) == []
    codes = [d.code for d in check_extensions(definition, [react.BINDING])]
    assert codes == ["invalid-value"]


def test_a_table_sends_its_filters_its_sort_and_its_page_to_the_api() -> None:
    output = files("project-tracker", "api")
    view = output["src/widgets/project-table/ui/project-table-view.tsx"]
    assert (
        "const listPage = useResource(JSON.stringify(query), () => projectApi.page(query)" in view
    )
    assert "    q: filters.search,\n" in view
    assert "    status: filters.status.length > 0 ? filters.status : null,\n" in view
    assert "    owner_id: filters.owner,\n" in view
    assert "    due_date_from: filters.due.from,\n" in view
    assert 'const VIEW_SORT: string[] = ["due_date"]; // @trace ui.views.project_table.sort' in view
    assert '  owner: "owner",\n' in view
    assert "server={{ ...pages, total, onChange: setPages }}" in view
    # The view does not filter or sort in the browser.
    assert "matches(" not in view
    assert "sortBy" not in view
    assert "src/shared/api/query.ts" not in output


def test_a_card_list_loads_one_page_and_a_boolean_filter_sends_only_true() -> None:
    view = files("project-tracker", "api")["src/widgets/person-cards/ui/person-cards-view.tsx"]
    assert "() => personApi.page(query)" in view
    assert "    active: filters.active || null,\n" in view
    assert "{rows.map((row) => (" in view
    assert "pageOf(" not in view


def test_a_tab_of_a_detail_view_sends_the_parameter_of_its_relation() -> None:
    output = files("project-tracker", "api")
    detail = output["src/widgets/project-detail/ui/project-detail-view.tsx"]
    assert "<TaskTableView params={{ project_id: record.id }} />" in detail
    assert "<PersonCardsView params={{ id: record.members }} />" in detail
    api = output["src/entities/person/api/person-api.ts"]
    assert '"id": "list"' in api
    assert 'sorts: ["name", "email", "role", "active"],' in api


def test_with_mock_data_the_views_filter_and_sort_in_the_browser() -> None:
    output = files("project-tracker", None)
    view = output["src/widgets/project-table/ui/project-table-view.tsx"]
    assert "all.filter((row) => matches(row, filters, lookups))" in view
    assert "where?: (record: Project) => boolean;" in view
    assert "src/shared/api/query.ts" in output
    detail = output["src/widgets/project-detail/ui/project-detail-view.tsx"]
    assert "<TaskTableView where={(row) => row.projectId === record.id} />" in detail


def test_a_field_path_is_a_quoted_parameter_name() -> None:
    text = (ROOT / "tests" / "fixtures" / "react-views.yaml").read_text()
    text = text.replace("title: Views }", "title: Views, x-react-data: api }", 1)
    definition = load_definition_text(text, "app.yaml")
    output = {f.path: f.content for f in generate(definition, react.BINDING).files}
    view = next(content for path, content in output.items() if path.endswith("item-table-view.tsx"))
    assert re.search(r'\n    "owner\.team_id": filters\.\w+', view)
    assert '"owner.team.lead.name"' in view
