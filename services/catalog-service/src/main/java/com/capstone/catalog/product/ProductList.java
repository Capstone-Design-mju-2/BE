package com.capstone.catalog.product;

import java.util.List;
import java.util.Map;

import org.springframework.jdbc.core.namedparam.MapSqlParameterSource;
import org.springframework.jdbc.core.namedparam.NamedParameterJdbcTemplate;
import org.springframework.stereotype.Repository;

@Repository
public class ProductList {

    // Ties fall back to the product id, so a product never shows up on two pages.
    private static final Map<String, String> ORDER = Map.of(
            "popular", "review_count DESC, id",
            "rating", "review_score DESC, id",
            "priceAsc", "price, id",
            "priceDesc", "price DESC, id");

    private static final String COUNT = "SELECT count(*) FROM products WHERE category_code = :category";

    private static final String PAGE = """
            SELECT id, name, brand_name, price, review_count, review_score
            FROM products
            WHERE category_code = :category
            ORDER BY %s
            LIMIT :size OFFSET :offset
            """;

    private final NamedParameterJdbcTemplate jdbcTemplate;

    public ProductList(NamedParameterJdbcTemplate jdbcTemplate) {
        this.jdbcTemplate = jdbcTemplate;
    }

    /** Null when no product has this category code: categories are known only through their products. */
    public Page list(String category, String sort, int page, int size) {
        var params = new MapSqlParameterSource()
                .addValue("category", category)
                .addValue("size", size)
                .addValue("offset", (long) page * size);
        long total = jdbcTemplate.queryForObject(COUNT, params, Long.class);
        if (total == 0) {
            return null;
        }
        var products = jdbcTemplate.query(PAGE.formatted(ORDER.get(sort)), params, (rs, row) -> new Product(
                rs.getLong("id"), rs.getString("name"), rs.getString("brand_name"), rs.getInt("price"),
                rs.getInt("review_count"), rs.getInt("review_score")));
        return new Page(total, products);
    }

    public record Page(long total, List<Product> products) {}

    public record Product(long productId, String name, String brand, int price, int reviewCount, int reviewScore) {}
}
