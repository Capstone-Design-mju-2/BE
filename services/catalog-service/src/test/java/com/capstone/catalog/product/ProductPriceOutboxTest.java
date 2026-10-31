package com.capstone.catalog.product;

import java.util.Map;

import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.boot.webmvc.test.autoconfigure.AutoConfigureMockMvc;
import org.springframework.context.annotation.Import;
import org.springframework.http.MediaType;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.test.context.bean.override.mockito.MockitoBean;
import org.springframework.test.web.servlet.MockMvc;
import org.springframework.test.web.servlet.ResultActions;

import com.capstone.catalog.TestcontainersConfiguration;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.Mockito.verifyNoInteractions;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.put;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

@SpringBootTest(properties = "catalog.index-sync=outbox")
@AutoConfigureMockMvc
@Import(TestcontainersConfiguration.class)
class ProductPriceOutboxTest {

    @Autowired
    MockMvc mockMvc;

    @Autowired
    JdbcTemplate jdbcTemplate;

    @MockitoBean
    ReviewIndex reviewIndex;

    long productId;

    @BeforeEach
    void seed() {
        jdbcTemplate.update("TRUNCATE products, reviews, review_survey_answers, product_ingredients, outbox RESTART IDENTITY");
        productId = jdbcTemplate.queryForObject("""
                INSERT INTO products (external_id, name, brand_name, category_code, normal_price, price,
                                      review_count, review_score, collected_on)
                VALUES (1, '수분크림', '브랜드', '104001', 20000, 15000, 10, 90, '2026-09-30') RETURNING id
                """, Long.class);
    }

    @Test
    void 가격을_바꾸면_같은_트랜잭션에_outbox_이벤트를_남기고_OpenSearch는_직접_고치지_않는다() throws Exception {
        changePrice(productId, "{\"price\": 30000}")
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.productId").value(productId))
                .andExpect(jsonPath("$.price").value(30000));

        assertThat(jdbcTemplate.queryForObject("SELECT price FROM products WHERE id = ?", Integer.class, productId))
                .isEqualTo(30000);
        assertThat(jdbcTemplate.queryForMap("""
                SELECT aggregate_type, aggregate_id, event_type, payload::text AS payload, processed_at FROM outbox
                """)).containsAllEntriesOf(Map.of("aggregate_type", "product", "aggregate_id", productId,
                        "event_type", "PriceChanged", "payload", "{\"price\": 30000, \"productId\": " + productId + "}"))
                .containsEntry("processed_at", null);
        verifyNoInteractions(reviewIndex);
    }

    @Test
    void 없는_상품이면_404이고_outbox에_아무것도_남지_않는다() throws Exception {
        changePrice(productId + 1, "{\"price\": 30000}").andExpect(status().isNotFound());

        assertThat(jdbcTemplate.queryForObject("SELECT count(*) FROM outbox", Integer.class)).isZero();
    }

    @Test
    void 가격이_없거나_음수면_400이다() throws Exception {
        for (String body : new String[] {"{}", "{\"price\": -1}"}) {
            changePrice(productId, body).andExpect(status().isBadRequest());
        }

        assertThat(jdbcTemplate.queryForObject("SELECT count(*) FROM outbox", Integer.class)).isZero();
    }

    private ResultActions changePrice(long id, String body) throws Exception {
        return mockMvc.perform(put("/internal/products/{id}/price", id)
                .contentType(MediaType.APPLICATION_JSON)
                .content(body));
    }
}
