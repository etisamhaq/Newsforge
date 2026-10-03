"""lock tables down for hosted Postgres (Supabase Data API)

Supabase exposes the `public` schema over its REST/GraphQL Data API to anyone holding the
publishable key. Newsforge never uses that API, so: enable Row Level Security with no policies
(denies every Data API role) and revoke the Data API roles' table privileges. The application
role owns the tables, so RLS does not affect it. On plain Postgres the role checks are no-ops.

Revision ID: 0002
Revises: 0001
Create Date: 2026-10-04
"""
from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None

TABLES = ("sources", "crawl_jobs", "pages", "articles", "raw_documents", "alembic_version")


def upgrade() -> None:
    if op.get_bind().dialect.name != "postgresql":
        return
    for table in TABLES:
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
    op.execute(
        f"""
        DO $$
        DECLARE r text;
        BEGIN
          FOREACH r IN ARRAY ARRAY['anon', 'authenticated'] LOOP
            IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = r) THEN
              EXECUTE format('REVOKE ALL ON {", ".join(TABLES)} FROM %I', r);
              EXECUTE format('REVOKE ALL ON ALL SEQUENCES IN SCHEMA public FROM %I', r);
            END IF;
          END LOOP;
        END $$;
        """
    )


def downgrade() -> None:
    if op.get_bind().dialect.name != "postgresql":
        return
    for table in TABLES:
        op.execute(f"ALTER TABLE {table} DISABLE ROW LEVEL SECURITY")
