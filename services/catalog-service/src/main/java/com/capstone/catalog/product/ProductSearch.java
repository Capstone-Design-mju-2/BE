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
    // Ranked by hits alone, name-only matches would never fit once more than limit products have matching reviews, so
    // every fifth slot is kept for them and the slots one side cannot fill go to the other (ADR-168).
    // A skin type only reorders evidence within that pool, so evidence keeps mentioning q (ADR-120).
    // Matching reviews are found in one pass and grouped; counting per product re-reads all reviews for every product.
    private static final String SEARCH = """
            WITH hits AS (
                SELECT r.product_id, count(*) AS hits
                FROM reviews r
                WHERE r.content ILIKE :pattern
                GROUP BY r.product_id
            ), candidates AS (
                SELECT p.id, p.name, p.brand_name, p.price, p.image_url, p.same_product_id, p.external_id,
                       p.review_count,
                       coalesce(h.hits, 0) AS hits
                FROM products p
                LEFT JOIN hits h ON h.product_id = p.id
                WHERE (CAST(:maxPrice AS integer) IS NULL OR p.price <= :maxPrice)
                  AND (CAST(:category AS text) IS NULL OR p.category_code = :category)
                  AND (CAST(:brand AS text) IS NULL OR p.brand_name = :brand)
                  AND (NOT :excludes OR (
                       EXISTS (SELECT 1 FROM product_ingredients i WHERE i.product_id = p.id)
                       AND NOT EXISTS (SELECT 1 FROM product_ingredients i
                                       WHERE i.product_id = p.id AND i.name IN (:excluded))))
                  AND (h.hits IS NOT NULL OR p.name ILIKE :pattern)
                  AND EXISTS (SELECT 1 FROM reviews r WHERE r.product_id = p.id)
            ), ranked AS (
                SELECT c.*,
                       row_number() OVER (PARTITION BY c.hits = 0 ORDER BY c.hits DESC, c.review_count DESC, c.id)
                           AS place,
                       count(*) FILTER (WHERE c.hits > 0) OVER () AS review_matches,
                       count(*) FILTER (WHERE c.hits = 0) OVER () AS name_matches
                FROM candidates c
            ), picked AS (
                -- Never more than :limit rows already. The LIMIT tells the planner so: without it the planner guesses
                -- about 1,900 rows here, the estimated cost passes jit_above_cost, and JIT adds about 300 ms.
                SELECT * FROM ranked
                WHERE place <= CASE WHEN hits > 0 THEN :limit - least(name_matches, :nameSlots)
                                    ELSE :limit - least(review_matches, :limit - least(name_matches, :nameSlots)) END
                LIMIT :limit
            )
            SELECT c.id, c.name, c.brand_name, c.price, c.image_url, c.same_product_id, c.external_id,
                   e.review_id, e.grade, e.content, e.skin_type
            FROM picked c
            CROSS JOIN LATERAL (
                SELECT r.id AS review_id, r.grade, r.content, r.written_at, r.skin_type,
                       (r.skin_type = :skinType) IS TRUE AS same_skin
                FROM reviews r
                WHERE r.product_id = c.id AND (c.hits = 0 OR r.content ILIKE :pattern)
                ORDER BY same_skin DESC, r.grade DESC, r.written_at DESC, r.id DESC
                LIMIT 2
            ) e
            ORDER BY c.hits DESC, c.review_count DESC, c.id, e.same_skin DESC, e.grade DESC, e.written_at DESC,
                     e.review_id DESC
            """;

    private final NamedParameterJdbcTemplate jdbcTemplate;

    public ProductSearch(NamedParameterJdbcTemplate jdbcTemplate) {
        this.jdbcTemplate = jdbcTemplate;
    }

    public List<Product> search(String q, Integer maxPrice, String category, String brand,
                                List<String> excludedIngredients, String skinType, int limit) {
        var params = new MapSqlParameterSource()
                .addValue("pattern", "%" + escapeLike(q) + "%")
                .addValue("maxPrice", maxPrice)
                .addValue("category", category)
                .addValue("brand", brand)
                .addValue("excludes", !excludedIngredients.isEmpty())
                // An empty list would expand to "IN ()", which is not valid SQL.
                .addValue("excluded", excludedIngredients.isEmpty() ? List.of("") : excludedIngredients)
                .addValue("skinType", skinType)
                .addValue("limit", limit)
                .addValue("nameSlots", limit / 5);

        Map<Long, Product> products = new LinkedHashMap<>();
        jdbcTemplate.query(SEARCH, params, rs -> {
            long id = rs.getLong("id");
            var product = products.get(id);
            if (product == null) {
                product = new Product(id, rs.getString("name"), rs.getString("brand_name"), rs.getInt("price"),
                        rs.getString("image_url"), Thumbnails.small(rs.getString("image_url")),
                        rs.getObject("same_product_id", Long.class),
                        ProductList.musinsaUrl(rs.getLong("external_id")), new ArrayList<>());
                products.put(id, product);
            }
            product.evidence().add(new Evidence(rs.getLong("review_id"), rs.getInt("grade"),
                    excerpt(rs.getString("content"), q), rs.getString("skin_type")));
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

    /** sameProductId marks a product Musinsa lists under several numbers; null when it is listed once (ADR-172). */
    public record Product(long productId, String name, String brand, int price, String imageUrl,
                          String thumbnailUrl, Long sameProductId, String productUrl, List<Evidence> evidence) {}

    public record Evidence(long reviewId, int rating, String excerpt, String skinType) {}
}
