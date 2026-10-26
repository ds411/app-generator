"""The lists that show the next page at their end (`pagination.mode: scroll`)."""

from pathlib import Path
from textwrap import dedent

import pytest

from appgen.bindings import nextjs, react
from appgen.dsl import load_definition_text, validate_definition
from appgen.dsl.ui.views import TableView
from appgen.gen import Binding
from appgen.gen.generator import generate

API_VIEWS = Path(__file__).parent / "fixtures" / "api-views.yaml"
BASE = dedent(
    """\
    version: 0
    app: { name: feed, title: Feed }
    entities:
      Post:
        crud: [create, list, update]
        display_field: title
        fields:
          title: { type: string, required: true }
          posted_at: { type: datetime, required: true }
    ui:
      views:
        post_table:
          kind: table
          entity: Post
          columns: { title: {}, posted_at: {} }
          sort: { field: posted_at, direction: desc }
          filters:
            search: { kind: search, fields: [title] }
          pagination: { mode: scroll, page_size: 25 }
        post_cards:
          kind: cards
          entity: Post
          card: { title: title, fields: [posted_at] }
          pagination: { mode: scroll, page_size: 9 }
    pages:
      posts: { path: /posts, title: Posts, content: { view: post_table } }
      cards: { path: /cards, title: Cards, content: { view: post_cards } }
    """
)
API = BASE.replace(
    "app: { name: feed, title: Feed }", "app: { name: feed, title: Feed, x-react-data: api }"
)


def codes(text: str) -> list[tuple[str, str | None]]:
    definition = load_definition_text(text, "app.yaml")
    return [(d.code, d.element_id) for d in validate_definition(definition)]


def files_of(text: str, binding: Binding) -> dict[str, str]:
    definition = load_definition_text(text, "app.yaml")
    return {f.path: f.content for f in generate(definition, binding).files}


def test_a_table_and_a_card_list_take_the_scroll_mode() -> None:
    assert codes(BASE) == []
    definition = load_definition_text(BASE, "app.yaml")
    assert definition.ui is not None
    view = definition.ui.views["post_table"]
    assert isinstance(view, TableView) and view.pagination is not None
    assert view.pagination.mode == "scroll"


def test_a_list_that_scrolls_has_no_page_sizes() -> None:
    text = BASE.replace("{ mode: scroll, page_size: 25 }", "{ mode: scroll, page_sizes: [10, 25] }")
    assert codes(text) == [("invalid-option", "ui.views.post_table.pagination")]


def test_the_default_mode_shows_pages() -> None:
    text = BASE.replace("mode: scroll, ", "")
    files = files_of(text, react.BINDING)
    assert "src/shared/ui/scroll-more.tsx" not in files
    assert "ListPagination" in files["src/widgets/post-cards/ui/post-cards-view.tsx"]


@pytest.mark.parametrize("binding", [nextjs.BINDING, react.BINDING], ids=["nextjs", "react"])
def test_the_lists_show_the_next_page_of_the_loaded_records(binding: Binding) -> None:
    files = files_of(BASE, binding)
    table = files["src/widgets/post-table/ui/post-table-view.tsx"]
    assert "          scroll\n" in table
    data_table = files["src/shared/ui/data-table.tsx"]
    assert 'import { ScrollMore } from "@/shared/ui/scroll-more";' in data_table
    assert "pageSize: value.pageSize + pageSize" in data_table
    cards = files["src/widgets/post-cards/ui/post-cards-view.tsx"]
    assert "rows.slice(0, shown).map((row) => (" in cards
    assert "onMore={() => setShown((value) => value + PAGE_SIZE)}" in cards
    assert "ListPagination" not in cards and "PAGE_SIZES" not in cards
    more = files["src/shared/ui/scroll-more.tsx"]
    assert "new IntersectionObserver(" in more
    assert "src/shared/lib/use-scroll-pages.ts" not in files


def test_with_the_api_each_load_is_one_page() -> None:
    files = files_of(API, react.BINDING)
    table = files["src/widgets/post-table/ui/post-table-view.tsx"]
    assert "const resource = useScrollPages(" in table
    assert "await postApi.page({ ...query, page, pageSize: PAGE_SIZE });" in table
    assert "scroll={{ loading: resource.loadingMore, onMore: resource.more }}" in table
    assert "useResource" not in table
    cards = files["src/widgets/post-cards/ui/post-cards-view.tsx"]
    assert (
        "<ScrollMore count={rows.length} total={total} loading={resource.loadingMore} "
        "onMore={resource.more} />"
    ) in cards
    assert "useState" not in cards
    hook = files["src/shared/lib/use-scroll-pages.ts"]
    assert "const pages = known.length === count - 1 ? [...known] : [];" in hook


def test_a_view_of_api_data_does_not_scroll() -> None:
    text = API_VIEWS.read_text().replace(
        "pagination: { page_size: 10, page_sizes: [10, 25] }", "pagination: { mode: scroll }", 1
    )
    definition = load_definition_text(text, str(API_VIEWS))
    found = [(d.code, d.element_id) for d in validate_definition(definition)]
    assert found == [("invalid-option", "ui.views.book_table.pagination")]
