package com.capstone.catalog.product;

import java.time.LocalDate;
import java.util.List;
import java.util.Map;

import org.springframework.jdbc.core.namedparam.MapSqlParameterSource;
import org.springframework.jdbc.core.namedparam.NamedParameterJdbcTemplate;
import org.springframework.stereotype.Repository;

@Repository
public class ReviewList {

    // Ties fall back to the newest, then the review id, so a review never shows up on two pages.
    private static final Map<String, String> ORDER = Map.of(
            "recent", "written_at DESC, id DESC",
            "rating", "grade DESC, written_at DESC, id DESC",
            "likes", "like_count DESC, written_at DESC, id DESC");

    private static final String PRODUCT_EXISTS = "SELECT EXISTS (SELECT 1 FROM products WHERE id = :productId)";

    private static final String MATCHING =
            "product_id = :productId AND (CAST(:skinType AS text) IS NULL OR skin_type = :skinType)";

    private static final String COUNT = "SELECT count(*) FROM reviews WHERE " + MATCHING;

    // The date a shopper in Korea saw on the review, not the UTC one. Reviews collected before 10/31 keep Musinsa's
    // lowercase "none" for a review without an option.
    private static final String PAGE = """
            SELECT id, grade, content, skin_type, NULLIF(option_text, 'none') AS option_text, like_count,
                   CAST(written_at AT TIME ZONE 'Asia/Seoul' AS date) AS written_on
            FROM reviews
            WHERE %s
            ORDER BY %s
            LIMIT :size OFFSET :offset
            """;

    private final NamedParameterJdbcTemplate jdbcTemplate;

    public ReviewList(NamedParameterJdbcTemplate jdbcTemplate) {
        this.jdbcTemplate = jdbcTemplate;
    }

    /** Null when there is no such product. */
    public Page list(long productId, String skinType, String sort, int page, int size) {
        var params = new MapSqlParameterSource()
                .addValue("productId", productId)
                .addValue("skinType", skinType)
                .addValue("size", size)
                .addValue("offset", (long) page * size);
        if (!jdbcTemplate.queryForObject(PRODUCT_EXISTS, params, Boolean.class)) {
            return null;
        }
        long total = jdbcTemplate.queryForObject(COUNT, params, Long.class);
        var reviews = jdbcTemplate.query(PAGE.formatted(MATCHING, ORDER.get(sort)), params, (rs, row) -> new Review(
                rs.getLong("id"), rs.getInt("grade"), rs.getString("content"), rs.getString("skin_type"),
                rs.getString("option_text"), rs.getInt("like_count"), rs.getObject("written_on", LocalDate.class)));
        return new Page(total, reviews);
    }

    public record Page(long total, List<Review> reviews) {}

    public record Review(long reviewId, int rating, String content, String skinType, String optionText, int likeCount,
                         LocalDate writtenAt) {}
}
