"""The records of the guests (ADR 0050): the DSL, the checks, and the FastAPI app."""

from pathlib import Path

import pytest

from appgen.bindings import fastapi, nextjs
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


def test_the_front_ends_have_a_gap_for_the_guests() -> None:
    # The Next.js app and the React app keep the records of a guest in #404.
    files = files_of(TEXT, nextjs.BINDING)
    assert "src/gaps/auth.guests.ext.ts" in files
