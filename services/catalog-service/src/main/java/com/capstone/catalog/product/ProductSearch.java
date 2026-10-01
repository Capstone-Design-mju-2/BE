package com.capstone.catalog.product;

import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

import org.springframework.jdbc.core.namedparam.MapSqlParameterSource;
import org.springframework.jdbc.core.namedparam.NamedParameterJdbcTemplate;
import org.springframework.stereotype.Repository;

@Repository
public class ProductSearch {

    static final int EXCERPT_LENGTH = 80;
    private static final int EXCERPT_LEAD = 20;

    // Products are ranked by how many reviews mention q. Name-only matches have no such
    // review, so their evidence falls back to the product's best reviews overall.
    private static final String SEARCH = """
            WITH matched AS (
                SELECT p.id, p.name, p.brand_name, p.price, p.review_count,
                       (SELECT count(*) FROM reviews r
                        WHERE r.product_id = p.id AND r.content ILIKE :pattern) AS hits,
                       p.name ILIKE :pattern AS name_hit
                FROM products p
                WHERE CAST(:maxPrice AS integer) IS NULL OR p.price <= :maxPrice
            ), candidates AS (
                SELECT * FROM matched m
                WHERE (m.hits > 0 OR m.name_hit)
                  AND EXISTS (SELECT 1 FROM reviews r WHERE r.product_id = m.id)
                ORDER BY m.hits DESC, m.review_count DESC, m.id
                LIMIT :limit
            )
            SELECT c.id, c.name, c.brand_name, c.price, e.review_id, e.grade, e.content
            FROM candidates c
            CROSS JOIN LATERAL (
                SELECT r.id AS review_id, r.grade, r.content, r.written_at
                FROM reviews r
                WHERE r.product_id = c.id AND (c.hits = 0 OR r.content ILIKE :pattern)
                ORDER BY r.grade DESC, r.written_at DESC, r.id DESC
                LIMIT 2
            ) e
            ORDER BY c.hits DESC, c.review_count DESC, c.id, e.grade DESC, e.written_at DESC, e.review_id DESC
            """;

    private final NamedParameterJdbcTemplate jdbcTemplate;

    public ProductSearch(NamedParameterJdbcTemplate jdbcTemplate) {
        this.jdbcTemplate = jdbcTemplate;
    }

    public List<Product> search(String q, Integer maxPrice, int limit) {
        var params = new MapSqlParameterSource()
                .addValue("pattern", "%" + escapeLike(q) + "%")
                .addValue("maxPrice", maxPrice)
                .addValue("limit", limit);

        Map<Long, Product> products = new LinkedHashMap<>();
        jdbcTemplate.query(SEARCH, params, rs -> {
            long id = rs.getLong("id");
            var product = products.get(id);
            if (product == null) {
                product = new Product(id, rs.getString("name"), rs.getString("brand_name"), rs.getInt("price"),
                        new ArrayList<>());
                products.put(id, product);
            }
            product.evidence().add(new Evidence(rs.getLong("review_id"), rs.getInt("grade"),
                    excerpt(rs.getString("content"), q)));
        });
        return List.copyOf(products.values());
    }

    static String excerpt(String content, String q) {
        String flat = content.strip().replaceAll("\\s+", " ");
        int[] codePoints = flat.codePoints().toArray();
        int hit = flat.indexOf(q);
        int start = hit < 0 ? 0 : Math.max(0, flat.codePointCount(0, hit) - EXCERPT_LEAD);
        int end = Math.min(codePoints.length, start + EXCERPT_LENGTH);
        return new String(codePoints, start, end - start);
    }

    private static String escapeLike(String q) {
        return q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_");
    }

    public record Product(long productId, String name, String brand, int price, List<Evidence> evidence) {}

    public record Evidence(long reviewId, int rating, String excerpt) {}
}
