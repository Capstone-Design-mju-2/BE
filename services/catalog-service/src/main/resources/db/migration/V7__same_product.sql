-- Musinsa lists some products under two or more numbers that show one pool of reviews (ADR-172). Such products are
-- marked with the smallest id among them, so product lists and chat cards show them once; a product listed once
-- stays null. Two products count as one when they have the same brand and review count and share at least ten
-- identical reviews of 40 characters or more. Computed once from the data loaded here: products loaded later stay
-- unmarked until this is computed again.
ALTER TABLE products ADD COLUMN same_product_id BIGINT;

WITH texts AS (
    SELECT product_id, md5(content) AS text_hash FROM reviews WHERE length(content) >= 40
), shared AS (
    SELECT a.product_id AS first_id, b.product_id AS second_id
    FROM texts a
    JOIN texts b ON a.text_hash = b.text_hash AND a.product_id < b.product_id
    GROUP BY a.product_id, b.product_id
    HAVING count(*) >= 10
), same AS (
    SELECT s.first_id, s.second_id
    FROM shared s
    JOIN products p ON p.id = s.first_id
    JOIN products q ON q.id = s.second_id
    WHERE p.brand_name = q.brand_name AND p.review_count = q.review_count
), marks AS (
    SELECT id, min(other_id) AS same_product_id
    FROM (SELECT first_id AS id, first_id AS other_id FROM same
          UNION ALL
          SELECT second_id, first_id FROM same) pairs
    GROUP BY id
)
UPDATE products p SET same_product_id = m.same_product_id FROM marks m WHERE p.id = m.id;
