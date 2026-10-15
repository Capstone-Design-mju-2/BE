CREATE TABLE orders (
    id          BIGSERIAL PRIMARY KEY,
    orderer_key VARCHAR(100) NOT NULL,
    total_price INT          NOT NULL CHECK (total_price >= 0),
    created_at  TIMESTAMPTZ  NOT NULL
);

CREATE TABLE order_items (
    id          BIGSERIAL PRIMARY KEY,
    order_id    BIGINT       NOT NULL REFERENCES orders(id),
    product_id  BIGINT       NOT NULL,
    option_key  VARCHAR(100) NOT NULL,
    name        VARCHAR(255) NOT NULL,
    unit_price  INT          NOT NULL CHECK (unit_price >= 0),
    quantity    INT          NOT NULL CHECK (quantity > 0)
);

CREATE INDEX idx_order_items_order_id ON order_items(order_id);