CREATE TABLE inventory (
    id         BIGSERIAL PRIMARY KEY,
    product_id BIGINT NOT NULL UNIQUE,
    quantity   INT NOT NULL DEFAULT 0 CHECK (quantity >= 0)
);
