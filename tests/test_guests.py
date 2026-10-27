"""The records of the guests (ADR 0050): the DSL, the checks, and the FastAPI app."""

from pathlib import Path

import pytest

from appgen.bindings import fastapi, nextjs, react
from appgen.bindings.react.api_client import DATA_KEY
from appgen.dsl import load_definition_text, validate_definition
from appgen.gen import Binding
from appgen.gen.generator import generate
from appgen.gen.render import GenerationError

ROOT = Path(__file__).parent.parent
FIXTURE = ROOT / "tests" / "fixtures" / "shop.yaml"
TEXT = FIXTURE.read_text(encoding="utf-8")
GUEST_OPERATIONS = (
    "operations: [list_cart_items, read_cart_item, create_cart_item, update_cart_item, "
    "delete_cart_item]"
)


def diagnostics(text: str) -> list[tuple[str, str]]:
    definition = load_definition_text(text, "app.yaml")
    return [(d.code, d.message) for d in validate_definition(definition)]


def files_of(text: str, binding: Binding = fastapi.BINDING) -> dict[str, str]:
    definition = load_definition_text(text, "app.yaml")
    return {f.path: f.content for f in generate(definition, binding).files}


def test_the_shop_is_valid() -> None:
    assert TEXT.count(GUEST_OPERATIONS) == 1
    assert diagnostics(TEXT) == []


def test_the_guests_need_the_roles() -> None:
    text = TEXT[: TEXT.index("# An admin may do all.")] + TEXT[TEXT.index("seed:") :]
    assert diagnostics(text) == [
        ("invalid-option", "'guests' needs the section 'access': the roles of the signed-in users.")
    ]


@pytest.mark.parametrize(
    ("entities", "code", "message"),
    [
        ("Cart: customer", "unknown-reference", "The entity 'Cart' does not exist."),
        (
            "Customer: cart_items",
            "invalid-value",
            "'Customer' is the user entity: a guest cannot own users.",
        ),
        (
            "CartItem: buyer",
            "unknown-reference",
            "The relation of 'CartItem' 'buyer' does not exist.",
        ),
        (
            "CartItem: product",
            "unsuitable-field",
            "The owner relation 'CartItem.product' must be a many-to-one relation to the user "
            "entity 'Customer'.",
        ),
    ],
)
def test_the_owner_of_a_guest_entity_is_a_relation_to_the_users(
    entities: str, code: str, message: str
) -> None:
    text = TEXT.replace("      CartItem: customer\n", f"      {entities}\n")
    # The operations of the guests need their entity.
    text = text.replace(GUEST_OPERATIONS, "operations: [list_cart_items]")
    found = [(c, m) for c, m in diagnostics(text) if "'list_cart_items'" not in m]
    assert found == [(code, message)]


def test_the_owner_of_a_guest_record_is_not_required() -> None:
    text = TEXT.replace(
        "        target: Customer\n        on_delete: cascade\n",
        "        target: Customer\n        required: true\n        on_delete: cascade\n",
    )
    assert diagnostics(text) == [
        (
            "unsuitable-field",
            "The owner relation 'CartItem.customer' must not be required: a record of a guest "
            "has no owner until it moves to a user.",
        )
    ]


@pytest.mark.parametrize(
    ("operations", "code", "message"),
    [
        ("[list_cart_item]", "unknown-reference", "The operation 'list_cart_item' does not exist."),
        (
            "[list_cart_items, read_product]",
            "invalid-value",
            "The operation 'read_product' is an operation of 'Product', which is not an entity "
            "of 'guests.entities'.",
        ),
        (
            "[list_cart_items, list_cart_items]",
            "duplicate-name",
            "The names in 'operations' must be unique.",
        ),
    ],
)
def test_the_guest_operations_are_operations_of_the_guest_entities(
    operations: str, code: str, message: str
) -> None:
    text = TEXT.replace(GUEST_OPERATIONS, f"operations: {operations}")
    assert diagnostics(text) == [(code, message)]


def test_a_guest_operation_is_not_public() -> None:
    text = TEXT.replace(
        "public_operations: [list_products, read_product]",
        "public_operations: [list_products, read_product, list_cart_items]",
    )
    assert diagnostics(text) == [
        (
            "invalid-value",
            "The operation 'list_cart_items' is public: a request without a sign-in uses all "
            "records, not the records of a guest.",
        )
    ]


def test_a_guest_calls_the_operations_of_records() -> None:
    text = TEXT.replace(
        "\npages:\n",
        "\noperations:\n  empty_cart: { kind: custom, entity: CartItem }\n\npages:\n",
    ).replace(GUEST_OPERATIONS, "operations: [list_cart_items, empty_cart]")
    assert diagnostics(text) == [
        (
            "unsuitable-operation",
            "A guest may call list, read, create, update, and delete operations, and "
            "'empty_cart' is a 'custom' operation.",
        )
    ]


def test_the_fastapi_app_gives_guest_tokens_and_moves_the_records() -> None:
    definition = load_definition_text(TEXT, "app.yaml")
    assert generate(definition, fastapi.BINDING).gaps == []
    files = files_of(TEXT)
    guests = files["app/core/guests.py"]
    assert '@router.post("", status_code=201, operation_id="start_guest_session")' in guests
    assert 'responses=problem_responses(400, 401, 422), operation_id="move_guest_records"' in guests
    assert ".values(customer_id=user.id, guest_id=None)" in guests
    assert "from app.core.guests import router as guests_router" in files["app/main.py"]


def test_the_guest_operations_accept_a_guest_or_a_user() -> None:
    files = files_of(TEXT)
    router = files["app/features/cart_items/router.py"]
    assert "dependencies=[Depends(check_guest_access)]" in router
    assert "check_access" not in router
    # The other operations need a user.
    assert "Depends(check_access)" in files["app/features/products/router.py"]
    operation = files["app/features/cart_items/list_cart_items.py"]
    assert 'Depends(guest_scope_of("read"))' in operation
    access = files["app/core/access.py"]
    assert 'GUEST_RULE = RecordRule(actions=frozenset({"read", "change"}), guest=True)' in access
    assert "return GUEST_RULE if entity in GUEST_ENTITIES else None" in access


def test_the_repository_keeps_the_records_of_a_guest_apart() -> None:
    files = files_of(TEXT)
    repository = files["app/features/cart_items/repository.py"]
    assert "return statement.where(CartItem.guest_id == scope.user)" in repository
    # A guest gives no owner to its records.
    assert 'values["customer_id"] = None\n        record.guest_id = scope.user' in repository
    model = files["app/features/cart_items/models.py"]
    assert "guest_id: Mapped[UUID | None] = mapped_column(index=True)" in model
    migration = files["migrations/versions/0001_schema.py"]
    assert 'sa.Column("guest_id", sa.Uuid(), nullable=True),' in migration
    assert 'op.create_index("ix_cart_items_guest_id", "cart_items", ["guest_id"])' in migration


def test_the_fastapi_app_tests_the_guests() -> None:
    files = files_of(TEXT)
    tests = files["tests/test_guests.py"]
    assert "async def test_a_guest_uses_its_own_cart_item_records(" in tests
    assert "async def test_the_cart_item_records_of_a_guest_move_to_the_user(" in tests
    conftest = files["tests/conftest.py"]
    assert "app.dependency_overrides[check_guest_access] = lambda: None" in conftest


@pytest.mark.parametrize(
    ("text", "message"),
    [
        (
            TEXT.replace(
                "      quantity: { type: integer",
                "      guest_id: { type: string }\n      quantity: { type: integer",
            ),
            "The entity 'CartItem' has a member 'guest_id', which is the column of the guest "
            "of a record. Rename the member.",
        ),
        (
            TEXT.replace(
                "\npages:\n",
                "\noperations:\n  move_guest_records: { kind: custom, entity: Product }\n\n"
                "pages:\n",
            ),
            "The operation 'move_guest_records' has the operation ID of an endpoint of the "
            "guests. Rename the operation.",
        ),
    ],
)
def test_the_guests_of_the_fastapi_app_have_their_own_names(text: str, message: str) -> None:
    assert diagnostics(text) == []
    with pytest.raises(GenerationError, match=message):
        files_of(text)


def test_an_app_without_guests_has_no_guest_code() -> None:
    text = TEXT[: TEXT.index("  guests:\n")] + TEXT[TEXT.index("# An admin may do all.") :]
    files = files_of(text)
    assert "app/core/guests.py" not in files
    assert "tests/test_guests.py" not in files
    assert not [path for path, content in files.items() if "guest_id" in content]


REACT_API = TEXT.replace("\napp:\n", f"\napp:\n  {DATA_KEY}: api\n", 1)


@pytest.mark.parametrize(
    ("text", "binding"),
    [(TEXT, nextjs.BINDING), (TEXT, react.BINDING), (REACT_API, react.BINDING)],
    ids=["nextjs", "react", "react-api"],
)
def test_the_front_ends_cover_the_guests(text: str, binding: Binding) -> None:
    definition = load_definition_text(text, "app.yaml")
    assert generate(definition, binding).gaps == []
    files = files_of(text, binding)
    permissions = files["src/shared/lib/permissions.ts"]
    assert 'export const GUEST_ENTITIES: readonly string[] = ["CartItem"];' in permissions
    assert "user === null ? roleMayCall(null, operation) || GUEST_OPERATIONS" in permissions
    # A guest sees the guest operations, and a link to the sign-in page.
    assert "visitorMayCall(role, userId, operation)" in "".join(
        content for path, content in files.items() if path.startswith("src/shared/lib/access")
    )
    button = files["src/features/sign-out/ui/sign-out-button.tsx"]
    assert '<Link\n        href="/sign-in"' in button


def test_the_nextjs_app_keeps_a_guest_session_in_a_cookie() -> None:
    files = files_of(TEXT, nextjs.BINDING)
    session = files["src/shared/auth/session.ts"]
    assert 'export const GUEST_COOKIE = "guest";' in session
    assert "export const GUEST_SECONDS = 2592000;" in session
    # A guest token has a guest ID, and a session token a user ID.
    assert "JSON.stringify({ guest: guestId, exp })" in session
    assert "  await moveGuestRecords(userId);\n  (await cookies()).set(SESSION_COOKIE" in session
    assert (
        "await tx.update(cartItemTable).set({ customerId: userId, guestId: null })"
        ".where(eq(cartItemTable.guestId, guest));"
    ) in session
    access = files["src/shared/auth/access.ts"]
    assert (
        "if (GUEST_OPERATIONS.includes(operation) && (await sessionUserId()) === null) {" in access
    )
    assert "return GUEST_ENTITIES.includes(entity) ? guestScope(action) : null;" in access
    schema = files["src/shared/db/schema/cart-item.ts"]
    assert '  guestId: uuid("guest_id"),' in schema
    assert 'index("ix_cart_item_guest_id").on(t.guestId),' in schema
    assert "guestId" not in files["src/shared/db/schema/product.ts"]


def test_the_nextjs_data_access_keeps_the_records_of_a_guest_apart() -> None:
    files = files_of(TEXT, nextjs.BINDING)
    actions = files["src/entities/cart-item/api/cart-item-actions.ts"]
    assert (
        "const owner = scope?.guest ? { customerId: null } : scope?.owner ? "
        "{ customerId: scope.user } : {};"
    ) in actions
    assert "const owner = scope?.guest ? { customerId: undefined }" in actions
    repository = files["src/shared/db/repository.ts"]
    assert "return guest === undefined ? inArray(this.table.id, []) : eq(guest, scope.user);" in (
        repository
    )
    assert "      values.guestId = options.scope.user;" in repository
    assert "      delete record.guestId;" in repository


def test_the_react_app_keeps_the_records_of_a_guest_in_the_mock_data() -> None:
    files = files_of(TEXT, react.BINDING)
    auth = files["src/shared/auth/index.ts"]
    # The session storage keeps the guest ID of the tab.
    assert 'const GUEST_KEY = "shop-guest-id";' in auth
    assert "let guestId = tabGuestId();" in auth
    assert "return { user: guestId, owner: false, where: {}, guest: true };" in auth
    # The sign-in and the sign-up move the records of the guest of the tab, and start a new guest.
    assert auth.count("moveGuestRecordsTo(user.id);") == 2
    assert "  moveGuestRecords(guestId, userId);\n  guestId = tabGuestId(true);" in auth
    store = files["src/shared/api/mock-store.ts"]
    assert "return (record as Record<string, unknown>).guestId === scope.user;" in store
    assert "return { [guest]: null, guestId: scope.user };" in store
    # The session storage keeps the records of the guests: the sign-in loads the page again.
    assert 'const GUEST_RECORDS_KEY = "shop-guest-records";' in store
    assert store.count("    this.keepGuestRecords();") == 1
    api = files["src/entities/cart-item/api/cart-item-api.ts"]
    assert '    guest: "customerId",' in api


def test_the_react_app_keeps_the_guest_token_of_the_api() -> None:
    files = files_of(REACT_API, react.BINDING)
    http = files["src/shared/api/http.ts"]
    assert 'const GUEST_KEY = "shop-guest";' in http
    assert 'guestRequest ??= apiRequest("POST", "/auth/guest")' in http
    assert "const token = accessToken() ?? guestToken();" in http
    auth = files["src/shared/auth/index.ts"]
    assert "  await moveGuestRecords();\n}" in auth
    assert 'await apiRequest("POST", "/auth/guest/move", { guest_token: guest });' in auth
    store = files["src/shared/api/http-store.ts"]
    assert store.count("if (this.shape.guest) {\n      await startGuestSession();") == 2
    api = files["src/entities/cart-item/api/cart-item-api.ts"]
    assert "  guest: true, // @trace auth.guests" in api
    assert "guest: true" not in files["src/entities/product/api/product-api.ts"]


@pytest.mark.parametrize("binding", [nextjs.BINDING, react.BINDING], ids=["nextjs", "react"])
@pytest.mark.parametrize(
    "text",
    [
        TEXT.replace(
            "      quantity: { type: integer",
            "      guest_id: { type: string }\n      quantity: { type: integer",
        ),
        TEXT.replace(
            "      product:\n        kind: many_to_one",
            "      guest: { kind: many_to_one, target: Product }\n"
            "      product:\n        kind: many_to_one",
        ),
    ],
    ids=["field", "relation"],
)
def test_the_guests_of_the_front_ends_have_their_own_key(text: str, binding: Binding) -> None:
    assert diagnostics(text) == []
    message = (
        "The entity 'CartItem' has a member with the key 'guestId', which is the key of the "
        "guest of a record. Rename the member."
    )
    with pytest.raises(GenerationError, match=message):
        files_of(text, binding)
