package com.capstone.catalog.product;

import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.regex.Pattern;

import org.springframework.jdbc.core.namedparam.MapSqlParameterSource;
import org.springframework.jdbc.core.namedparam.NamedParameterJdbcTemplate;
import org.springframework.stereotype.Repository;

@Repository
public class ProductSearch {

    static final int EXCERPT_LENGTH = 80;
    private static final int EXCERPT_LEAD = 20;
    private static final Pattern SENTENCE_END = Pattern.compile("[.!?]\\s|\\n");

    // Products are ranked by how many reviews mention q. Name-only matches have no such
    // review, so their evidence falls back to the product's best reviews overall.
    // Matching reviews are found in one pass and grouped; counting per product re-reads all reviews for every product.
    private static final String SEARCH = """
            WITH hits AS (
                SELECT r.product_id, count(*) AS hits
                FROM reviews r
                WHERE r.content ILIKE :pattern
                GROUP BY r.product_id
            ), candidates AS (
                SELECT p.id, p.name, p.brand_name, p.price, p.review_count, coalesce(h.hits, 0) AS hits
                FROM products p
                LEFT JOIN hits h ON h.product_id = p.id
                WHERE (CAST(:maxPrice AS integer) IS NULL OR p.price <= :maxPrice)
                  AND (CAST(:category AS text) IS NULL OR p.category_code = :category)
                  AND (CAST(:brand AS text) IS NULL OR p.brand_name = :brand)
                  AND (h.hits IS NOT NULL OR p.name ILIKE :pattern)
                  AND EXISTS (SELECT 1 FROM reviews r WHERE r.product_id = p.id)
                ORDER BY hits DESC, p.review_count DESC, p.id
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

    public List<Product> search(String q, Integer maxPrice, String category, String brand, int limit) {
        var params = new MapSqlParameterSource()
                .addValue("pattern", "%" + escapeLike(q) + "%")
                .addValue("maxPrice", maxPrice)
                .addValue("category", category)
                .addValue("brand", brand)
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
        String text = content.strip().replaceAll("\\s*\\n\\s*", "\n").replaceAll("\\h+", " ");
        var match = Pattern.compile(Pattern.quote(q), Pattern.CASE_INSENSITIVE | Pattern.UNICODE_CASE).matcher(text);
        if (!match.find()) {
            return slice(text, 0, EXCERPT_LENGTH);
        }
        var sentenceEnd = SENTENCE_END.matcher(text).region(0, match.start());
        int start = 0;
        while (sentenceEnd.find()) {
            start = sentenceEnd.end();
        }
        if (text.codePointCount(start, match.end()) <= EXCERPT_LENGTH) {
            return slice(text, start, EXCERPT_LENGTH);
        }
        // The sentence is too long to show q from its start. Look back for a space only within
        // EXCERPT_LEAD so q stays inside the excerpt.
        int back = Math.min(EXCERPT_LEAD, text.codePointCount(start, match.start()));
        int lead = text.offsetByCodePoints(match.start(), -back);
        if (lead == start) {
            return slice(text, start, EXCERPT_LENGTH);
        }
        int space = text.lastIndexOf(' ', lead - 1);
        if (space >= start && text.codePointCount(space + 1, lead) < EXCERPT_LEAD) {
            lead = space + 1;
        }
        return "…" + slice(text, lead, EXCERPT_LENGTH - 1);
    }

    private static String slice(String text, int from, int maxCodePoints) {
        int length = Math.min(maxCodePoints, text.codePointCount(from, text.length()));
        return text.substring(from, text.offsetByCodePoints(from, length)).replace('\n', ' ');
    }

    private static String escapeLike(String q) {
        return q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_");
    }

    public record Product(long productId, String name, String brand, int price, List<Evidence> evidence) {}

    public record Evidence(long reviewId, int rating, String excerpt) {}
}
