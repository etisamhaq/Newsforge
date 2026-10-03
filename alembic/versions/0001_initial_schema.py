"""initial schema

Revision ID: 0001
Revises: 
Create Date: 2026-10-04
"""
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = '0001'
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table('sources',
    sa.Column('id', sa.BigInteger().with_variant(sa.Integer(), 'sqlite'), autoincrement=True, nullable=False),
    sa.Column('name', sa.String(length=200), nullable=False),
    sa.Column('base_url', sa.Text(), nullable=False),
    sa.Column('domain', sa.String(length=255), nullable=False),
    sa.Column('allowed_domains', sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql'), nullable=False),
    sa.Column('start_urls', sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql'), nullable=False),
    sa.Column('feed_urls', sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql'), nullable=False),
    sa.Column('sitemap_urls', sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql'), nullable=False),
    sa.Column('include_patterns', sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql'), nullable=False),
    sa.Column('exclude_patterns', sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql'), nullable=False),
    sa.Column('enabled', sa.Boolean(), nullable=False),
    sa.Column('crawl_interval_minutes', sa.Integer(), nullable=False),
    sa.Column('max_pages', sa.Integer(), nullable=False),
    sa.Column('max_depth', sa.Integer(), nullable=False),
    sa.Column('min_delay_seconds', sa.Float(), nullable=False),
    sa.Column('render_mode', sa.String(length=16), nullable=False),
    sa.Column('store_raw_html', sa.Boolean(), nullable=False),
    sa.Column('discover_links', sa.Boolean(), nullable=False),
    sa.Column('last_crawl_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('next_crawl_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_sources')),
    sa.UniqueConstraint('name', name=op.f('uq_sources_name'))
    )
    op.create_index(op.f('ix_sources_domain'), 'sources', ['domain'], unique=False)
    op.create_index(op.f('ix_sources_next_crawl_at'), 'sources', ['next_crawl_at'], unique=False)
    op.create_table('articles',
    sa.Column('id', sa.BigInteger().with_variant(sa.Integer(), 'sqlite'), autoincrement=True, nullable=False),
    sa.Column('source_id', sa.BigInteger().with_variant(sa.Integer(), 'sqlite'), nullable=True),
    sa.Column('url', sa.Text(), nullable=False),
    sa.Column('canonical_url', sa.Text(), nullable=False),
    sa.Column('canonical_hash', sa.String(length=64), nullable=False),
    sa.Column('title', sa.Text(), nullable=True),
    sa.Column('description', sa.Text(), nullable=True),
    sa.Column('body', sa.Text(), nullable=True),
    sa.Column('authors', sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql'), nullable=False),
    sa.Column('published_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('modified_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('image_url', sa.Text(), nullable=True),
    sa.Column('category', sa.String(length=255), nullable=True),
    sa.Column('tags', sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql'), nullable=False),
    sa.Column('language', sa.String(length=16), nullable=True),
    sa.Column('site_name', sa.String(length=255), nullable=True),
    sa.Column('word_count', sa.Integer(), nullable=False),
    sa.Column('content_hash', sa.String(length=64), nullable=True),
    sa.Column('simhash', sa.BigInteger(), nullable=True),
    sa.Column('simhash_b0', sa.Integer(), nullable=True),
    sa.Column('simhash_b1', sa.Integer(), nullable=True),
    sa.Column('simhash_b2', sa.Integer(), nullable=True),
    sa.Column('simhash_b3', sa.Integer(), nullable=True),
    sa.Column('extraction_method', sa.String(length=64), nullable=True),
    sa.Column('confidence', sa.Float(), nullable=False),
    sa.Column('article_score', sa.Float(), nullable=False),
    sa.Column('duplicate_of_id', sa.BigInteger().with_variant(sa.Integer(), 'sqlite'), nullable=True),
    sa.Column('extra', sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql'), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['duplicate_of_id'], ['articles.id'], name=op.f('fk_articles_duplicate_of_id_articles'), ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['source_id'], ['sources.id'], name=op.f('fk_articles_source_id_sources'), ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_articles')),
    sa.UniqueConstraint('canonical_hash', name=op.f('uq_articles_canonical_hash'))
    )
    op.create_index(op.f('ix_articles_content_hash'), 'articles', ['content_hash'], unique=False)
    op.create_index(op.f('ix_articles_duplicate_of_id'), 'articles', ['duplicate_of_id'], unique=False)
    op.create_index(op.f('ix_articles_language'), 'articles', ['language'], unique=False)
    op.create_index(op.f('ix_articles_published_at'), 'articles', ['published_at'], unique=False)
    op.create_index(op.f('ix_articles_simhash_b0'), 'articles', ['simhash_b0'], unique=False)
    op.create_index(op.f('ix_articles_simhash_b1'), 'articles', ['simhash_b1'], unique=False)
    op.create_index(op.f('ix_articles_simhash_b2'), 'articles', ['simhash_b2'], unique=False)
    op.create_index(op.f('ix_articles_simhash_b3'), 'articles', ['simhash_b3'], unique=False)
    op.create_index(op.f('ix_articles_source_id'), 'articles', ['source_id'], unique=False)
    op.create_index('ix_articles_source_published', 'articles', ['source_id', 'published_at'], unique=False)
    op.create_table('crawl_jobs',
    sa.Column('id', sa.BigInteger().with_variant(sa.Integer(), 'sqlite'), autoincrement=True, nullable=False),
    sa.Column('source_id', sa.BigInteger().with_variant(sa.Integer(), 'sqlite'), nullable=False),
    sa.Column('status', sa.String(length=16), nullable=False),
    sa.Column('trigger', sa.String(length=16), nullable=False),
    sa.Column('task_id', sa.String(length=64), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('started_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('finished_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('pages_fetched', sa.Integer(), nullable=False),
    sa.Column('pages_failed', sa.Integer(), nullable=False),
    sa.Column('pages_skipped', sa.Integer(), nullable=False),
    sa.Column('articles_found', sa.Integer(), nullable=False),
    sa.Column('articles_new', sa.Integer(), nullable=False),
    sa.Column('articles_updated', sa.Integer(), nullable=False),
    sa.Column('duplicates', sa.Integer(), nullable=False),
    sa.Column('error', sa.Text(), nullable=True),
    sa.Column('stats', sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql'), nullable=False),
    sa.ForeignKeyConstraint(['source_id'], ['sources.id'], name=op.f('fk_crawl_jobs_source_id_sources'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_crawl_jobs'))
    )
    op.create_index(op.f('ix_crawl_jobs_source_id'), 'crawl_jobs', ['source_id'], unique=False)
    op.create_index(op.f('ix_crawl_jobs_status'), 'crawl_jobs', ['status'], unique=False)
    op.create_table('pages',
    sa.Column('id', sa.BigInteger().with_variant(sa.Integer(), 'sqlite'), autoincrement=True, nullable=False),
    sa.Column('source_id', sa.BigInteger().with_variant(sa.Integer(), 'sqlite'), nullable=True),
    sa.Column('url', sa.Text(), nullable=False),
    sa.Column('url_hash', sa.String(length=64), nullable=False),
    sa.Column('status_code', sa.Integer(), nullable=True),
    sa.Column('etag', sa.String(length=512), nullable=True),
    sa.Column('last_modified', sa.String(length=128), nullable=True),
    sa.Column('content_hash', sa.String(length=64), nullable=True),
    sa.Column('is_article', sa.Boolean(), nullable=True),
    sa.Column('fetch_count', sa.Integer(), nullable=False),
    sa.Column('failure_count', sa.Integer(), nullable=False),
    sa.Column('last_error', sa.Text(), nullable=True),
    sa.Column('last_fetched_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['source_id'], ['sources.id'], name=op.f('fk_pages_source_id_sources'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_pages')),
    sa.UniqueConstraint('url_hash', name=op.f('uq_pages_url_hash'))
    )
    op.create_index(op.f('ix_pages_source_id'), 'pages', ['source_id'], unique=False)
    op.create_table('raw_documents',
    sa.Column('id', sa.BigInteger().with_variant(sa.Integer(), 'sqlite'), autoincrement=True, nullable=False),
    sa.Column('article_id', sa.BigInteger().with_variant(sa.Integer(), 'sqlite'), nullable=True),
    sa.Column('page_id', sa.BigInteger().with_variant(sa.Integer(), 'sqlite'), nullable=True),
    sa.Column('url', sa.Text(), nullable=False),
    sa.Column('status_code', sa.Integer(), nullable=True),
    sa.Column('headers', sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql'), nullable=False),
    sa.Column('content_gzip', sa.LargeBinary(), nullable=False),
    sa.Column('rendered', sa.Boolean(), nullable=False),
    sa.Column('fetched_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['article_id'], ['articles.id'], name=op.f('fk_raw_documents_article_id_articles'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['page_id'], ['pages.id'], name=op.f('fk_raw_documents_page_id_pages'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_raw_documents'))
    )
    op.create_index(op.f('ix_raw_documents_article_id'), 'raw_documents', ['article_id'], unique=False)
    op.create_index(op.f('ix_raw_documents_page_id'), 'raw_documents', ['page_id'], unique=False)

    # Postgres full-text search: generated tsvector column + GIN index.
    if op.get_bind().dialect.name == "postgresql":
        op.execute(
            """
            ALTER TABLE articles ADD COLUMN search_vector tsvector
            GENERATED ALWAYS AS (
                setweight(to_tsvector('simple', coalesce(title, '')), 'A') ||
                setweight(to_tsvector('simple', coalesce(description, '')), 'B') ||
                setweight(to_tsvector('simple', coalesce(body, '')), 'C')
            ) STORED
            """
        )
        op.execute("CREATE INDEX ix_articles_search_vector ON articles USING GIN (search_vector)")


def downgrade() -> None:
    op.drop_index(op.f('ix_raw_documents_page_id'), table_name='raw_documents')
    op.drop_index(op.f('ix_raw_documents_article_id'), table_name='raw_documents')
    op.drop_table('raw_documents')
    op.drop_index(op.f('ix_pages_source_id'), table_name='pages')
    op.drop_table('pages')
    op.drop_index(op.f('ix_crawl_jobs_status'), table_name='crawl_jobs')
    op.drop_index(op.f('ix_crawl_jobs_source_id'), table_name='crawl_jobs')
    op.drop_table('crawl_jobs')
    op.drop_index('ix_articles_source_published', table_name='articles')
    op.drop_index(op.f('ix_articles_source_id'), table_name='articles')
    op.drop_index(op.f('ix_articles_simhash_b3'), table_name='articles')
    op.drop_index(op.f('ix_articles_simhash_b2'), table_name='articles')
    op.drop_index(op.f('ix_articles_simhash_b1'), table_name='articles')
    op.drop_index(op.f('ix_articles_simhash_b0'), table_name='articles')
    op.drop_index(op.f('ix_articles_published_at'), table_name='articles')
    op.drop_index(op.f('ix_articles_language'), table_name='articles')
    op.drop_index(op.f('ix_articles_duplicate_of_id'), table_name='articles')
    op.drop_index(op.f('ix_articles_content_hash'), table_name='articles')
    op.drop_table('articles')
    op.drop_index(op.f('ix_sources_next_crawl_at'), table_name='sources')
    op.drop_index(op.f('ix_sources_domain'), table_name='sources')
    op.drop_table('sources')
