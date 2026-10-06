ALTER TABLE inventory DROP CONSTRAINT inventory_product_id_key;

ALTER TABLE inventory
    ADD COLUMN option_key VARCHAR(100) NOT NULL DEFAULT '',
    ADD COLUMN name       VARCHAR(255) NOT NULL DEFAULT '',
    ADD COLUMN price      INT          NOT NULL DEFAULT 0 CHECK (price >= 0);

ALTER TABLE inventory ADD CONSTRAINT inventory_product_option_key UNIQUE (product_id, option_key);