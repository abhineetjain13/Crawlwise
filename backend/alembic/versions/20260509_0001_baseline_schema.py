"""Baseline schema for clean-start deployments.

Revision ID: 20260509_0001
Revises:
Create Date: 2026-05-09 00:00:00
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "20260509_0001"
down_revision: str | None = None
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


_UPGRADE_SQL: tuple[str, ...] = (
    """
    CREATE TABLE domain_cookie_memory (
        id SERIAL NOT NULL,
        domain VARCHAR(255) NOT NULL,
        storage_state JSONB NOT NULL,
        state_fingerprint VARCHAR(128) NOT NULL,
        updated_at TIMESTAMP WITH TIME ZONE NOT NULL,
        created_at TIMESTAMP WITH TIME ZONE NOT NULL,
        PRIMARY KEY (id)
    )
    """,
    "CREATE INDEX ix_domain_cookie_memory_domain ON domain_cookie_memory (domain)",
    "CREATE UNIQUE INDEX uq_domain_cookie_memory_domain ON domain_cookie_memory (domain)",
    """
    CREATE TABLE domain_memory (
        id SERIAL NOT NULL,
        domain VARCHAR(255) NOT NULL,
        surface VARCHAR(40) NOT NULL,
        platform VARCHAR(40),
        selectors JSONB NOT NULL,
        updated_at TIMESTAMP WITH TIME ZONE NOT NULL,
        created_at TIMESTAMP WITH TIME ZONE NOT NULL,
        PRIMARY KEY (id)
    )
    """,
    "CREATE INDEX ix_domain_memory_domain ON domain_memory (domain)",
    "CREATE INDEX ix_domain_memory_surface ON domain_memory (surface)",
    """
    CREATE TABLE domain_run_profiles (
        id SERIAL NOT NULL,
        domain VARCHAR(255) NOT NULL,
        surface VARCHAR(40) NOT NULL,
        profile JSONB NOT NULL,
        updated_at TIMESTAMP WITH TIME ZONE NOT NULL,
        created_at TIMESTAMP WITH TIME ZONE NOT NULL,
        PRIMARY KEY (id)
    )
    """,
    "CREATE INDEX ix_domain_run_profiles_domain ON domain_run_profiles (domain)",
    "CREATE INDEX ix_domain_run_profiles_surface ON domain_run_profiles (surface)",
    "CREATE UNIQUE INDEX uq_domain_run_profiles_domain_surface ON domain_run_profiles (domain, surface)",
    """
    CREATE TABLE host_protection_memory (
        id SERIAL NOT NULL,
        host VARCHAR(255) NOT NULL,
        hard_block_count INTEGER NOT NULL,
        browser_first_until TIMESTAMP WITH TIME ZONE,
        proxy_required_until TIMESTAMP WITH TIME ZONE,
        last_block_vendor VARCHAR(64),
        last_block_status_code INTEGER,
        last_block_method VARCHAR(32),
        last_blocked_at TIMESTAMP WITH TIME ZONE,
        last_success_at TIMESTAMP WITH TIME ZONE,
        last_success_method VARCHAR(32),
        updated_at TIMESTAMP WITH TIME ZONE NOT NULL,
        created_at TIMESTAMP WITH TIME ZONE NOT NULL,
        PRIMARY KEY (id)
    )
    """,
    "CREATE INDEX ix_host_protection_memory_host ON host_protection_memory (host)",
    "CREATE UNIQUE INDEX uq_host_protection_memory_host ON host_protection_memory (host)",
    """
    CREATE TABLE llm_configs (
        id SERIAL NOT NULL,
        provider VARCHAR(30) NOT NULL,
        model VARCHAR(255) NOT NULL,
        api_key_encrypted TEXT NOT NULL,
        task_type VARCHAR(60) NOT NULL,
        per_domain_daily_budget_usd NUMERIC(10, 2) NOT NULL,
        global_session_budget_usd NUMERIC(10, 2) NOT NULL,
        is_active BOOLEAN NOT NULL,
        created_at TIMESTAMP WITH TIME ZONE NOT NULL,
        PRIMARY KEY (id)
    )
    """,
    """
    CREATE TABLE users (
        id SERIAL NOT NULL,
        email VARCHAR(255) NOT NULL,
        hashed_password VARCHAR(255) NOT NULL,
        role VARCHAR(20) NOT NULL,
        is_active BOOLEAN NOT NULL,
        token_version INTEGER NOT NULL,
        created_at TIMESTAMP WITH TIME ZONE NOT NULL,
        updated_at TIMESTAMP WITH TIME ZONE NOT NULL,
        PRIMARY KEY (id)
    )
    """,
    "CREATE UNIQUE INDEX ix_users_email ON users (email)",
    """
    CREATE TABLE crawl_runs (
        id SERIAL NOT NULL,
        user_id INTEGER NOT NULL,
        run_type VARCHAR(20) NOT NULL,
        url TEXT NOT NULL,
        status VARCHAR(20) NOT NULL,
        surface VARCHAR(40) NOT NULL,
        settings JSONB NOT NULL,
        requested_fields JSONB NOT NULL,
        result_summary JSONB NOT NULL,
        queue_owner VARCHAR(64),
        lease_expires_at TIMESTAMP WITH TIME ZONE,
        last_heartbeat_at TIMESTAMP WITH TIME ZONE,
        claim_count INTEGER NOT NULL,
        last_claimed_at TIMESTAMP WITH TIME ZONE,
        updated_at TIMESTAMP WITH TIME ZONE NOT NULL,
        created_at TIMESTAMP WITH TIME ZONE NOT NULL,
        completed_at TIMESTAMP WITH TIME ZONE,
        PRIMARY KEY (id),
        FOREIGN KEY(user_id) REFERENCES users (id)
    )
    """,
    "CREATE INDEX ix_crawl_runs_status ON crawl_runs (status)",
    "CREATE INDEX ix_crawl_runs_user_id ON crawl_runs (user_id)",
    """
    CREATE TABLE crawl_logs (
        id SERIAL NOT NULL,
        run_id INTEGER NOT NULL,
        level VARCHAR(20) NOT NULL,
        message TEXT NOT NULL,
        created_at TIMESTAMP WITH TIME ZONE NOT NULL,
        PRIMARY KEY (id),
        FOREIGN KEY(run_id) REFERENCES crawl_runs (id) ON DELETE CASCADE
    )
    """,
    "CREATE INDEX ix_crawl_logs_run_id ON crawl_logs (run_id)",
    """
    CREATE TABLE crawl_records (
        id SERIAL NOT NULL,
        run_id INTEGER NOT NULL,
        source_url TEXT NOT NULL,
        url_identity_key VARCHAR(64),
        content_fingerprint VARCHAR(64),
        data JSONB NOT NULL,
        raw_data JSONB NOT NULL,
        discovered_data JSONB NOT NULL,
        source_trace JSONB NOT NULL,
        raw_html_path TEXT,
        enrichment_status VARCHAR(32) DEFAULT 'unenriched' NOT NULL,
        enriched_at TIMESTAMP WITH TIME ZONE,
        created_at TIMESTAMP WITH TIME ZONE NOT NULL,
        PRIMARY KEY (id),
        FOREIGN KEY(run_id) REFERENCES crawl_runs (id) ON DELETE CASCADE
    )
    """,
    "CREATE INDEX ix_crawl_records_enrichment_status ON crawl_records (enrichment_status)",
    "CREATE INDEX ix_crawl_records_run_content_fp ON crawl_records (run_id, content_fingerprint)",
    "CREATE INDEX ix_crawl_records_run_id ON crawl_records (run_id)",
    "CREATE UNIQUE INDEX uq_crawl_records_run_identity ON crawl_records (run_id, url_identity_key) WHERE url_identity_key IS NOT NULL",
    """
    CREATE TABLE data_enrichment_jobs (
        id SERIAL NOT NULL,
        user_id INTEGER NOT NULL,
        source_run_id INTEGER,
        status VARCHAR(32) NOT NULL,
        options JSONB NOT NULL,
        summary JSONB NOT NULL,
        updated_at TIMESTAMP WITH TIME ZONE NOT NULL,
        created_at TIMESTAMP WITH TIME ZONE NOT NULL,
        completed_at TIMESTAMP WITH TIME ZONE,
        PRIMARY KEY (id),
        FOREIGN KEY(user_id) REFERENCES users (id),
        FOREIGN KEY(source_run_id) REFERENCES crawl_runs (id) ON DELETE SET NULL
    )
    """,
    "CREATE INDEX ix_data_enrichment_jobs_source_run_id ON data_enrichment_jobs (source_run_id)",
    "CREATE INDEX ix_data_enrichment_jobs_status ON data_enrichment_jobs (status)",
    "CREATE INDEX ix_data_enrichment_jobs_user_id ON data_enrichment_jobs (user_id)",
    """
    CREATE TABLE domain_field_feedback (
        id SERIAL NOT NULL,
        domain VARCHAR(255) NOT NULL,
        surface VARCHAR(40) NOT NULL,
        field_name VARCHAR(128) NOT NULL,
        action VARCHAR(32) NOT NULL,
        source_kind VARCHAR(32) NOT NULL,
        source_value TEXT,
        source_run_id INTEGER,
        payload JSONB NOT NULL,
        created_at TIMESTAMP WITH TIME ZONE NOT NULL,
        PRIMARY KEY (id),
        FOREIGN KEY(source_run_id) REFERENCES crawl_runs (id) ON DELETE SET NULL
    )
    """,
    "CREATE INDEX ix_domain_field_feedback_domain ON domain_field_feedback (domain)",
    "CREATE INDEX ix_domain_field_feedback_domain_surface ON domain_field_feedback (domain, surface)",
    "CREATE INDEX ix_domain_field_feedback_field_name ON domain_field_feedback (field_name)",
    "CREATE INDEX ix_domain_field_feedback_source_run_id ON domain_field_feedback (source_run_id)",
    "CREATE INDEX ix_domain_field_feedback_surface ON domain_field_feedback (surface)",
    """
    CREATE TABLE llm_cost_log (
        id SERIAL NOT NULL,
        run_id INTEGER,
        provider VARCHAR(30) NOT NULL,
        model VARCHAR(255) NOT NULL,
        task_type VARCHAR(60) NOT NULL,
        input_tokens INTEGER NOT NULL,
        output_tokens INTEGER NOT NULL,
        cost_usd NUMERIC(10, 4) NOT NULL,
        domain VARCHAR(255) NOT NULL,
        outcome VARCHAR(20) NOT NULL,
        error_category VARCHAR(60) NOT NULL,
        error_message TEXT NOT NULL,
        created_at TIMESTAMP WITH TIME ZONE NOT NULL,
        PRIMARY KEY (id),
        CONSTRAINT ck_llm_cost_log_outcome CHECK (outcome in ('success', 'error')),
        FOREIGN KEY(run_id) REFERENCES crawl_runs (id)
    )
    """,
    "CREATE INDEX ix_llm_cost_log_run_id ON llm_cost_log (run_id)",
    """
    CREATE TABLE product_intelligence_jobs (
        id SERIAL NOT NULL,
        user_id INTEGER NOT NULL,
        source_run_id INTEGER,
        status VARCHAR(32) NOT NULL,
        options JSONB NOT NULL,
        summary JSONB NOT NULL,
        updated_at TIMESTAMP WITH TIME ZONE NOT NULL,
        created_at TIMESTAMP WITH TIME ZONE NOT NULL,
        completed_at TIMESTAMP WITH TIME ZONE,
        PRIMARY KEY (id),
        FOREIGN KEY(user_id) REFERENCES users (id),
        FOREIGN KEY(source_run_id) REFERENCES crawl_runs (id) ON DELETE SET NULL
    )
    """,
    "CREATE INDEX ix_product_intelligence_jobs_source_run_id ON product_intelligence_jobs (source_run_id)",
    "CREATE INDEX ix_product_intelligence_jobs_status ON product_intelligence_jobs (status)",
    "CREATE INDEX ix_product_intelligence_jobs_user_id ON product_intelligence_jobs (user_id)",
    """
    CREATE TABLE review_promotions (
        id SERIAL NOT NULL,
        run_id INTEGER NOT NULL,
        domain VARCHAR(255) NOT NULL,
        surface VARCHAR(40) NOT NULL,
        approved_schema JSONB NOT NULL,
        field_mapping JSONB NOT NULL,
        updated_at TIMESTAMP WITH TIME ZONE NOT NULL,
        created_at TIMESTAMP WITH TIME ZONE NOT NULL,
        PRIMARY KEY (id),
        FOREIGN KEY(run_id) REFERENCES crawl_runs (id) ON DELETE CASCADE
    )
    """,
    "CREATE INDEX ix_review_promotions_domain ON review_promotions (domain)",
    "CREATE INDEX ix_review_promotions_run_id ON review_promotions (run_id)",
    """
    CREATE TABLE enriched_products (
        id SERIAL NOT NULL,
        job_id INTEGER NOT NULL,
        source_run_id INTEGER,
        source_record_id INTEGER,
        source_url TEXT NOT NULL,
        status VARCHAR(32) NOT NULL,
        price_normalized JSONB,
        color_family TEXT,
        size_normalized JSONB,
        size_system VARCHAR(32),
        gender_normalized VARCHAR(32),
        materials_normalized JSONB,
        availability_normalized VARCHAR(32),
        seo_keywords JSONB,
        category_path TEXT,
        taxonomy_version VARCHAR(32),
        intent_attributes JSONB,
        audience JSONB,
        style_tags JSONB,
        ai_discovery_tags JSONB,
        suggested_bundles JSONB,
        diagnostics JSONB NOT NULL,
        updated_at TIMESTAMP WITH TIME ZONE NOT NULL,
        created_at TIMESTAMP WITH TIME ZONE NOT NULL,
        PRIMARY KEY (id),
        FOREIGN KEY(job_id) REFERENCES data_enrichment_jobs (id) ON DELETE CASCADE,
        FOREIGN KEY(source_run_id) REFERENCES crawl_runs (id) ON DELETE SET NULL,
        FOREIGN KEY(source_record_id) REFERENCES crawl_records (id) ON DELETE SET NULL
    )
    """,
    "CREATE INDEX ix_enriched_products_job_id ON enriched_products (job_id)",
    "CREATE INDEX ix_enriched_products_source_record_id ON enriched_products (source_record_id)",
    "CREATE INDEX ix_enriched_products_source_run_id ON enriched_products (source_run_id)",
    "CREATE INDEX ix_enriched_products_status ON enriched_products (status)",
    "CREATE UNIQUE INDEX uq_enriched_products_source_record ON enriched_products (source_record_id) WHERE source_record_id IS NOT NULL",
    """
    CREATE TABLE product_intelligence_source_products (
        id SERIAL NOT NULL,
        job_id INTEGER NOT NULL,
        source_run_id INTEGER,
        source_record_id INTEGER,
        source_url TEXT NOT NULL,
        brand VARCHAR(255) NOT NULL,
        normalized_brand VARCHAR(255) NOT NULL,
        title TEXT NOT NULL,
        sku VARCHAR(255) NOT NULL,
        mpn VARCHAR(255) NOT NULL,
        gtin VARCHAR(255) NOT NULL,
        price FLOAT,
        currency VARCHAR(16) NOT NULL,
        image_url TEXT NOT NULL,
        is_private_label BOOLEAN NOT NULL,
        payload JSONB NOT NULL,
        created_at TIMESTAMP WITH TIME ZONE NOT NULL,
        PRIMARY KEY (id),
        FOREIGN KEY(job_id) REFERENCES product_intelligence_jobs (id) ON DELETE CASCADE,
        FOREIGN KEY(source_run_id) REFERENCES crawl_runs (id) ON DELETE SET NULL,
        FOREIGN KEY(source_record_id) REFERENCES crawl_records (id) ON DELETE SET NULL
    )
    """,
    "CREATE INDEX ix_product_intelligence_source_products_brand ON product_intelligence_source_products (brand)",
    "CREATE INDEX ix_product_intelligence_source_products_job_id ON product_intelligence_source_products (job_id)",
    "CREATE INDEX ix_product_intelligence_source_products_normalized_brand ON product_intelligence_source_products (normalized_brand)",
    "CREATE INDEX ix_product_intelligence_source_products_source_record_id ON product_intelligence_source_products (source_record_id)",
    "CREATE INDEX ix_product_intelligence_source_products_source_run_id ON product_intelligence_source_products (source_run_id)",
    """
    CREATE TABLE product_intelligence_candidates (
        id SERIAL NOT NULL,
        job_id INTEGER NOT NULL,
        source_product_id INTEGER NOT NULL,
        candidate_crawl_run_id INTEGER,
        url TEXT NOT NULL,
        domain VARCHAR(255) NOT NULL,
        source_type VARCHAR(64) NOT NULL,
        query_used TEXT NOT NULL,
        search_rank INTEGER NOT NULL,
        status VARCHAR(32) NOT NULL,
        payload JSONB NOT NULL,
        updated_at TIMESTAMP WITH TIME ZONE NOT NULL,
        created_at TIMESTAMP WITH TIME ZONE NOT NULL,
        PRIMARY KEY (id),
        FOREIGN KEY(job_id) REFERENCES product_intelligence_jobs (id) ON DELETE CASCADE,
        FOREIGN KEY(source_product_id) REFERENCES product_intelligence_source_products (id) ON DELETE CASCADE,
        FOREIGN KEY(candidate_crawl_run_id) REFERENCES crawl_runs (id) ON DELETE SET NULL
    )
    """,
    "CREATE INDEX ix_product_intelligence_candidates_candidate_crawl_run_id ON product_intelligence_candidates (candidate_crawl_run_id)",
    "CREATE INDEX ix_product_intelligence_candidates_domain ON product_intelligence_candidates (domain)",
    "CREATE INDEX ix_product_intelligence_candidates_job_id ON product_intelligence_candidates (job_id)",
    "CREATE INDEX ix_product_intelligence_candidates_source_product_id ON product_intelligence_candidates (source_product_id)",
    "CREATE INDEX ix_product_intelligence_candidates_status ON product_intelligence_candidates (status)",
    """
    CREATE TABLE product_intelligence_matches (
        id SERIAL NOT NULL,
        job_id INTEGER NOT NULL,
        source_product_id INTEGER NOT NULL,
        candidate_id INTEGER NOT NULL,
        candidate_record_id INTEGER,
        score FLOAT NOT NULL,
        score_label VARCHAR(32) NOT NULL,
        review_status VARCHAR(32) NOT NULL,
        source_price FLOAT,
        candidate_price FLOAT,
        currency VARCHAR(16) NOT NULL,
        availability TEXT NOT NULL,
        candidate_url TEXT NOT NULL,
        candidate_domain VARCHAR(255) NOT NULL,
        score_reasons JSONB NOT NULL,
        llm_enrichment JSONB NOT NULL,
        updated_at TIMESTAMP WITH TIME ZONE NOT NULL,
        created_at TIMESTAMP WITH TIME ZONE NOT NULL,
        PRIMARY KEY (id),
        FOREIGN KEY(job_id) REFERENCES product_intelligence_jobs (id) ON DELETE CASCADE,
        FOREIGN KEY(source_product_id) REFERENCES product_intelligence_source_products (id) ON DELETE CASCADE,
        FOREIGN KEY(candidate_id) REFERENCES product_intelligence_candidates (id) ON DELETE CASCADE,
        FOREIGN KEY(candidate_record_id) REFERENCES crawl_records (id) ON DELETE SET NULL
    )
    """,
    "CREATE INDEX ix_product_intelligence_matches_candidate_domain ON product_intelligence_matches (candidate_domain)",
    "CREATE INDEX ix_product_intelligence_matches_candidate_id ON product_intelligence_matches (candidate_id)",
    "CREATE INDEX ix_product_intelligence_matches_candidate_record_id ON product_intelligence_matches (candidate_record_id)",
    "CREATE INDEX ix_product_intelligence_matches_job_id ON product_intelligence_matches (job_id)",
    "CREATE INDEX ix_product_intelligence_matches_job_source ON product_intelligence_matches (job_id, source_product_id)",
    "CREATE INDEX ix_product_intelligence_matches_review_status ON product_intelligence_matches (review_status)",
    "CREATE INDEX ix_product_intelligence_matches_score ON product_intelligence_matches (score)",
    "CREATE INDEX ix_product_intelligence_matches_source_product_id ON product_intelligence_matches (source_product_id)",
)

_DOWNGRADE_TABLES: tuple[str, ...] = (
    "product_intelligence_matches",
    "product_intelligence_candidates",
    "product_intelligence_source_products",
    "enriched_products",
    "review_promotions",
    "product_intelligence_jobs",
    "llm_cost_log",
    "domain_field_feedback",
    "data_enrichment_jobs",
    "crawl_records",
    "crawl_logs",
    "crawl_runs",
    "users",
    "llm_configs",
    "host_protection_memory",
    "domain_run_profiles",
    "domain_memory",
    "domain_cookie_memory",
)


def upgrade() -> None:
    for statement in _UPGRADE_SQL:
        op.execute(statement)


def downgrade() -> None:
    for table_name in _DOWNGRADE_TABLES:
        op.execute(f"DROP TABLE IF EXISTS {table_name} CASCADE")
