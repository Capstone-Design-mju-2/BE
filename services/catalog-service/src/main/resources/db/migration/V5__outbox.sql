-- Price changes the indexer still has to apply to the review index (ADR-121). processed_at stays null until it has.
CREATE TABLE outbox (
    id             BIGSERIAL   PRIMARY KEY,
    aggregate_type VARCHAR(50) NOT NULL,
    aggregate_id   BIGINT      NOT NULL,
    event_type     VARCHAR(50) NOT NULL,
    payload        JSONB       NOT NULL,
    created_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    processed_at   TIMESTAMPTZ
);

CREATE INDEX idx_outbox_pending ON outbox (id) WHERE processed_at IS NULL;
