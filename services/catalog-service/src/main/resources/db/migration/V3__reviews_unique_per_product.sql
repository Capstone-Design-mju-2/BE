-- Musinsa shares reviews between variant products (set, size), so one review number can belong to several products.
-- Each product keeps its own copy of the review.

ALTER TABLE reviews DROP CONSTRAINT reviews_external_id_key;
ALTER TABLE reviews ADD CONSTRAINT reviews_product_id_external_id_key UNIQUE (product_id, external_id);
