"""workspaces: per-team data isolation, per-workspace members, quotas and daily usage

Existing data moves into one workspace named "Newsforge" (the original workspace; people listed
in ADMIN_EMAILS become its admins). Uniqueness that used to be global (source names, page URLs,
canonical article URLs, member emails) becomes per workspace.

Revision ID: 0004
Revises: 0003
Create Date: 2026-10-04
"""
import sqlalchemy as sa

from alembic import op

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None

BIGINT = sa.BigInteger().with_variant(sa.Integer(), "sqlite")
SCOPED = ("sources", "crawl_jobs", "pages", "articles", "members")


def upgrade() -> None:
    op.create_table(
        "workspaces",
        sa.Column("id", BIGINT, autoincrement=True, nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("created_by_email", sa.String(length=320), nullable=True),
        sa.Column("created_by_user_id", sa.String(length=64), nullable=True),
        sa.Column("max_sources", sa.Integer(), nullable=True),
        sa.Column("max_pages_per_day", sa.Integer(), nullable=True),
        sa.Column("max_pages_per_crawl", sa.Integer(), nullable=True),
        sa.Column("min_crawl_interval_minutes", sa.Integer(), nullable=True),
        sa.Column("max_concurrent_crawls", sa.Integer(), nullable=True),
        sa.Column("llm_calls_per_day", sa.Integer(), nullable=True),
        sa.Column("max_members", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_workspaces")),
    )
    op.create_index(op.f("ix_workspaces_created_by_user_id"), "workspaces", ["created_by_user_id"])
    op.create_table(
        "workspace_usage",
        sa.Column("workspace_id", BIGINT, nullable=False),
        sa.Column("day", sa.Date(), nullable=False),
        sa.Column("pages", sa.Integer(), nullable=False),
        sa.Column("llm_calls", sa.Integer(), nullable=False),
        sa.Column("crawls", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], name=op.f("fk_workspace_usage_workspace_id_workspaces"), ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("workspace_id", "day", name=op.f("pk_workspace_usage")),
    )

    # The original workspace that owns all existing data.
    conn = op.get_bind()
    default_id = conn.execute(
        sa.text("INSERT INTO workspaces (name, created_at, updated_at) VALUES ('Newsforge', now(), now()) RETURNING id")
    ).scalar_one()

    for table in SCOPED:
        op.add_column(table, sa.Column("workspace_id", BIGINT, nullable=True))
        conn.execute(sa.text(f"UPDATE {table} SET workspace_id = :id"), {"id": default_id})
        op.alter_column(table, "workspace_id", nullable=False)
        op.create_foreign_key(
            op.f(f"fk_{table}_workspace_id_workspaces"), table, "workspaces", ["workspace_id"], ["id"], ondelete="CASCADE"
        )

    # Global uniqueness becomes per-workspace uniqueness.
    op.drop_constraint("uq_sources_name", "sources", type_="unique")
    op.create_unique_constraint("uq_sources_workspace_name", "sources", ["workspace_id", "name"])
    op.drop_constraint("uq_pages_url_hash", "pages", type_="unique")
    op.create_unique_constraint("uq_pages_workspace_url", "pages", ["workspace_id", "url_hash"])
    op.drop_constraint("uq_articles_canonical_hash", "articles", type_="unique")
    op.create_unique_constraint("uq_articles_workspace_canonical", "articles", ["workspace_id", "canonical_hash"])
    op.drop_constraint("uq_members_email", "members", type_="unique")
    op.drop_constraint("uq_members_user_id", "members", type_="unique")
    op.create_unique_constraint("uq_members_workspace_email", "members", ["workspace_id", "email"])
    op.create_unique_constraint("uq_members_workspace_user", "members", ["workspace_id", "user_id"])

    op.create_index(op.f("ix_sources_workspace_id"), "sources", ["workspace_id"])
    op.create_index(op.f("ix_crawl_jobs_workspace_id"), "crawl_jobs", ["workspace_id"])
    op.create_index(op.f("ix_members_workspace_id"), "members", ["workspace_id"])
    op.create_index(op.f("ix_members_email"), "members", ["email"])
    op.create_index(op.f("ix_members_user_id"), "members", ["user_id"])
    op.create_index("ix_articles_workspace_published", "articles", ["workspace_id", "published_at"])

    # Same Data API lockdown as 0002/0003 for the new tables.
    for table in ("workspaces", "workspace_usage"):
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
    op.execute(
        """
        DO $$
        DECLARE r text;
        BEGIN
          FOREACH r IN ARRAY ARRAY['anon', 'authenticated'] LOOP
            IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = r) THEN
              EXECUTE format('REVOKE ALL ON workspaces, workspace_usage FROM %I', r);
              EXECUTE format('REVOKE ALL ON ALL SEQUENCES IN SCHEMA public FROM %I', r);
            END IF;
          END LOOP;
        END $$;
        """
    )


def downgrade() -> None:
    # Only safe while a single workspace exists (uniqueness becomes global again).
    op.drop_index("ix_articles_workspace_published", table_name="articles")
    for name, table in (("ix_members_user_id", "members"), ("ix_members_email", "members"), ("ix_members_workspace_id", "members"),
                        ("ix_crawl_jobs_workspace_id", "crawl_jobs"), ("ix_sources_workspace_id", "sources")):
        op.drop_index(op.f(name), table_name=table)
    op.drop_constraint("uq_members_workspace_user", "members", type_="unique")
    op.drop_constraint("uq_members_workspace_email", "members", type_="unique")
    op.create_unique_constraint("uq_members_user_id", "members", ["user_id"])
    op.create_unique_constraint("uq_members_email", "members", ["email"])
    op.drop_constraint("uq_articles_workspace_canonical", "articles", type_="unique")
    op.create_unique_constraint("uq_articles_canonical_hash", "articles", ["canonical_hash"])
    op.drop_constraint("uq_pages_workspace_url", "pages", type_="unique")
    op.create_unique_constraint("uq_pages_url_hash", "pages", ["url_hash"])
    op.drop_constraint("uq_sources_workspace_name", "sources", type_="unique")
    op.create_unique_constraint("uq_sources_name", "sources", ["name"])
    for table in SCOPED:
        op.drop_constraint(op.f(f"fk_{table}_workspace_id_workspaces"), table, type_="foreignkey")
        op.drop_column(table, "workspace_id")
    op.drop_table("workspace_usage")
    op.drop_index(op.f("ix_workspaces_created_by_user_id"), table_name="workspaces")
    op.drop_table("workspaces")
