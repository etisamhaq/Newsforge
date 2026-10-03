"""members (per-person access) and who triggered each crawl

Revision ID: 0003
Revises: 0002
Create Date: 2026-10-04
"""
import sqlalchemy as sa

from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "members",
        sa.Column("id", sa.BigInteger().with_variant(sa.Integer(), "sqlite"), autoincrement=True, nullable=False),
        sa.Column("email", sa.String(length=320), nullable=False),
        sa.Column("user_id", sa.String(length=64), nullable=True),
        sa.Column("role", sa.String(length=16), nullable=False),
        sa.Column("invited_by", sa.String(length=320), nullable=True),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_members")),
        sa.UniqueConstraint("email", name=op.f("uq_members_email")),
        sa.UniqueConstraint("user_id", name=op.f("uq_members_user_id")),
    )
    op.add_column("crawl_jobs", sa.Column("triggered_by", sa.String(length=320), nullable=True))

    # Same lockdown as 0002 for the new table on hosted Postgres (Supabase Data API).
    if op.get_bind().dialect.name == "postgresql":
        op.execute("ALTER TABLE members ENABLE ROW LEVEL SECURITY")
        op.execute(
            """
            DO $$
            DECLARE r text;
            BEGIN
              FOREACH r IN ARRAY ARRAY['anon', 'authenticated'] LOOP
                IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = r) THEN
                  EXECUTE format('REVOKE ALL ON members FROM %I', r);
                  EXECUTE format('REVOKE ALL ON ALL SEQUENCES IN SCHEMA public FROM %I', r);
                END IF;
              END LOOP;
            END $$;
            """
        )


def downgrade() -> None:
    op.drop_column("crawl_jobs", "triggered_by")
    op.drop_table("members")
