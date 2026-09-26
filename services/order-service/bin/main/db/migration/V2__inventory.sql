CREATE TABLE inventory (
    id         BIGSERIAL PRIMARY KEY,
    product_id BIGINT NOT NULL,
    quantity   INT NOT NULL DEFAULT 0
);
