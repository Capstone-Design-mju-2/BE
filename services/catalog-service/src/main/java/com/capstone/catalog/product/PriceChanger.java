package com.capstone.catalog.product;

import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Repository;
import org.springframework.transaction.annotation.Transactional;

@Repository
public class PriceChanger {

    private static final String UPDATE_PRICE = "UPDATE products SET price = ? WHERE id = ?";

    private static final String INSERT_EVENT = """
            INSERT INTO outbox (aggregate_type, aggregate_id, event_type, payload)
            VALUES ('product', ?, 'PriceChanged', jsonb_build_object('productId', ?::bigint, 'price', ?::int))
            """;

    private final JdbcTemplate jdbcTemplate;

    public PriceChanger(JdbcTemplate jdbcTemplate) {
        this.jdbcTemplate = jdbcTemplate;
    }

    /** False when there is no such product. With outbox the event commits or rolls back together with the price. */
    @Transactional
    public boolean change(long productId, int price, boolean outbox) {
        if (jdbcTemplate.update(UPDATE_PRICE, price, productId) == 0) {
            return false;
        }
        if (outbox) {
            jdbcTemplate.update(INSERT_EVENT, productId, productId, price);
        }
        return true;
    }
}
