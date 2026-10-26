"""The metadata of the pages: the checks, the tags of the Next.js pages, the sitemap,
robots.txt, and the description of the React pages."""

from textwrap import dedent

import pytest

from appgen.bindings import nextjs, react
from appgen.dsl import load_definition_text, validate_definition
from appgen.gen import Binding
from appgen.gen.generator import generate

BASE = dedent(
    """\
    version: 0
    app: { name: blog, title: Blog }
    storage: { kind: local }
    entities:
      Author:
        display_field: name
        fields:
          name: { type: string, required: true }
      Post:
        display_field: title
        fields:
          title: { type: string, required: true }
          slug: { type: string, required: true, unique: true }
          summary: { type: text }
          cover: { type: image }
          link: { type: url }
          published_on: { type: date }
        relations:
          author: { kind: many_to_one, target: Author, required: true }
    ui:
      views:
        post_table: { kind: table, entity: Post, columns: { title: {} } }
        post_detail: { kind: detail, entity: Post, header: { title: title } }
    pages:
      posts:
        path: /posts
        title: Posts
        meta: { description: All the posts., image: /posts.png }
        content: { view: post_table }
      post:
        path: /authors/{author_id}/posts/{id}
        title: Post
        entity: Post
        meta: { description: $record.summary, image: $record.cover }
        content: { view: post_detail }
      about: { path: /about, title: About, content: { custom: true } }
    """
)
AUTH = (
    BASE.replace(
        "  Author:\n",
        "  Member:\n    fields:\n"
        "      email: { type: email, required: true, unique: true }\n  Author:\n",
        1,
    )
    + "auth: { user_entity: Member, username_field: email, public_pages: [posts, post] }\n"
)
POST = "app/(bare)/authors/[author_id]/posts/[id]/page.tsx"


def codes(text: str) -> list[tuple[str, str | None]]:
    definition = load_definition_text(text, "app.yaml")
    return [(d.code, d.element_id) for d in validate_definition(definition)]


def files_of(text: str, binding: Binding) -> dict[str, str]:
    definition = load_definition_text(text, "app.yaml")
    return {f.path: f.content for f in generate(definition, binding).files}


def test_a_page_takes_meta() -> None:
    assert codes(BASE) == []
    assert codes(AUTH) == []
    definition = load_definition_text(BASE, "app.yaml")
    meta = definition.pages["post"].meta
    assert meta is not None and meta.id == "pages.post.meta"
    assert (meta.description, meta.image) == ("$record.summary", "$record.cover")


@pytest.mark.parametrize(
    ("old", "new", "code"),
    [
        ("image: /posts.png", "image: posts.png", "invalid-value"),
        ("image: /posts.png", "image: $record.cover", "invalid-option"),
        ("description: $record.summary", "description: $record.text", "unknown-reference"),
        ("description: $record.summary", "description: $record.published_on", "unsuitable-field"),
        ("image: $record.cover", "image: $record.summary", "unsuitable-field"),
    ],
)
def test_the_checks_of_the_metadata(old: str, new: str, code: str) -> None:
    found = codes(BASE.replace(old, new))
    assert [c for c, _ in found] == [code]
    assert found[0][1] in ("pages.posts.meta", "pages.post.meta")


def test_a_record_value_needs_a_public_page() -> None:
    found = codes(AUTH.replace("public_pages: [posts, post]", "public_pages: [posts]"))
    assert found == [("invalid-option", "pages.post.meta"), ("invalid-option", "pages.post.meta")]
    # A text is fine on a protected page.
    assert codes(AUTH.replace("public_pages: [posts, post]", "public_pages: [post]")) == []


def test_an_image_is_a_url_or_a_path_or_a_url_field() -> None:
    text = BASE.replace("image: /posts.png", "image: https://example.com/posts.png")
    assert codes(text.replace("image: $record.cover", "image: $record.link")) == []


def test_the_nextjs_pages_render_the_metadata() -> None:
    files = files_of(BASE, nextjs.BINDING)
    posts = files["app/(bare)/posts/page.tsx"]
    assert 'import { pageMetadata } from "@/shared/lib/site";' in posts
    assert (
        'return pageMetadata({ title: "Posts", description: "All the posts.", '
        'image: "/posts.png" });'
    ) in posts
    post = files[POST]
    assert "export async function generateMetadata({ params }: " in post
    assert (
        "const record = (await postRepository.exists(id)) ? await postRepository.get(id) : null;"
    ) in post
    assert (
        'return pageMetadata({ title: "Post", description: record?.summary, '
        "image: record?.cover?.url });"
    ) in post
    site = files["src/shared/lib/site.ts"]
    assert "openGraph: {" in site and 'card: images ? "summary_large_image" : "summary"' in site
    assert "PUBLIC_URL=\n" in files[".env.example"]
    # A page without meta keeps its title only.
    assert (
        'export const metadata: Metadata = { title: "About" };'
        in files["app/(bare)/about/page.tsx"]
    )


def test_the_sitemap_has_the_public_pages_and_their_records() -> None:
    files = files_of(BASE, nextjs.BINDING)
    sitemap = files["app/sitemap.ts"]
    assert "const postRecords = (await postRepository.list()).items;" in sitemap
    assert "{ url: `${base}/posts` }," in sitemap
    assert (
        "...postRecords.map((record) => ({ url: `${base}/authors/"
        "${encodeURIComponent(String(record.authorId))}/posts/"
        "${encodeURIComponent(String(record.id))}` })),"
    ) in sitemap
    assert "/about" not in sitemap
    robots = files["app/robots.ts"]
    assert 'rules: { userAgent: "*", allow: "/", disallow: "/api/" },' in robots
    assert "sitemap: `${await siteUrl()}/sitemap.xml`," in robots


def test_the_sitemap_leaves_out_the_pages_that_it_cannot_list() -> None:
    # A path parameter without a value in each record.
    text = BASE.replace("/authors/{author_id}/posts/{id}", "/posts/{published_on}/{id}")
    sitemap = files_of(text, nextjs.BINDING)["app/sitemap.ts"]
    assert "postRepository" not in sitemap and "/posts` }," in sitemap
    # A required field is a key of the records.
    text = BASE.replace("/authors/{author_id}/posts/{id}", "/posts/{slug}")
    sitemap = files_of(text, nextjs.BINDING)["app/sitemap.ts"]
    assert "/posts/${encodeURIComponent(String(record.slug))}" in sitemap
    # A protected page is not in the sitemap.
    sitemap = files_of(
        AUTH.replace("public_pages: [posts, post]", "public_pages: [post]"), nextjs.BINDING
    )["app/sitemap.ts"]
    assert "`${base}/posts`" not in sitemap and "postRecords" in sitemap


def test_without_meta_the_apps_have_no_sitemap() -> None:
    text = "".join(line for line in BASE.splitlines(keepends=True) if "meta:" not in line)
    files = files_of(text, nextjs.BINDING)
    assert not {"app/sitemap.ts", "app/robots.ts", "src/shared/lib/site.ts"} & set(files)
    assert "PUBLIC_URL" not in files[".env.example"]
    assert "src/shared/lib/use-description.ts" not in files_of(text, react.BINDING)


def test_the_react_pages_set_the_description() -> None:
    files = files_of(BASE, react.BINDING)
    posts = files["src/pages/posts/ui/posts-page.tsx"]
    assert 'useDescription("All the posts."); // @trace pages.posts.meta' in posts
    post = files["src/pages/post/ui/post-page.tsx"]
    assert 'const record = useResource(`post:meta:${id}`, () => postApi.get(id ?? ""));' in post
    assert 'return record.status === "success" ? (record.data.summary ?? null) : null;' in post
    assert "useDescription(usePageDescription());" in post
    hook = files["src/shared/lib/use-description.ts"]
    assert "export function useDescription(description: string | null | undefined): void {" in hook
