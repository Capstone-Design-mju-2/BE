-- One row per ingredient name, parsed by scripts/load_ingredients.py (ADR-75, ADR-97).
-- A product without rows has an unknown ingredient list, so any ingredient exclusion leaves it out.
-- source says where the list came from: the Musinsa product notice, or Glowpick when the notice only says
-- "see the detail page" (ADR-75). One product's rows all share one source.

CREATE TABLE product_ingredients (
    product_id      BIGINT       NOT NULL REFERENCES products (id),
    name            VARCHAR(100) NOT NULL,
    source          VARCHAR(20)  NOT NULL CHECK (source IN ('musinsa', 'glowpick')),
    source_url      VARCHAR(200),
    PRIMARY KEY (product_id, name)
);
