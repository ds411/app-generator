# Created by appgen once. appgen never changes or deletes this file.
# @trace:manual app file
"""Create the schema of the app definition `project-tracker`.

appgen creates this migration once, from the definition of the first
run, and never changes it. After a change to the definition, generate
the app again, and make the next migration with
`uv run alembic revision --autogenerate -m "<change>"` (ADR 0009). The
models carry the traces to the definition elements. This file has
only the trace of the app, so it does not get invalid when an element
of the definition goes away.

Revision ID: 0001
Revises:
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create the tables, then the foreign keys, so that the order of the tables is free."""
    op.create_table(
        "projects",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column(
            "status",
            sa.Enum(
                "planned",
                "active",
                "done",
                name="ck_projects_status",
                native_enum=False,
                create_constraint=True,
                length=7,
            ),
            nullable=True,
        ),
        sa.PrimaryKeyConstraint("id", name="pk_projects"),
    )
    op.create_table(
        "tasks",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("title", sa.String(), nullable=False),
        sa.Column("due_date", sa.Date(), nullable=True),
        sa.Column("done", sa.Boolean(), nullable=True),
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_tasks"),
    )
    with op.batch_alter_table("tasks") as batch:
        batch.create_foreign_key(
            "fk_tasks_project_id_projects",
            "projects",
            ["project_id"],
            ["id"],
            ondelete="CASCADE",
        )
    op.create_index("ix_tasks_project_id", "tasks", ["project_id"])


def downgrade() -> None:
    """Drop the join tables and the foreign keys, then the tables."""
    with op.batch_alter_table("tasks") as batch:
        batch.drop_constraint("fk_tasks_project_id_projects", type_="foreignkey")
    op.drop_table("tasks")
    op.drop_table("projects")
