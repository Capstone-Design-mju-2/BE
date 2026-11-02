package com.capstone.catalog.product;

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
import org.springframework.web.client.ResourceAccessException;

import com.capstone.catalog.TestcontainersConfiguration;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.Mockito.doAnswer;
import static org.mockito.Mockito.doThrow;
import static org.mockito.Mockito.verify;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.put;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

@SpringBootTest(properties = "catalog.index-sync=dual-write")
@AutoConfigureMockMvc
@Import(TestcontainersConfiguration.class)
class ProductPriceDualWriteTest {

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
    void 가격이_커밋된_뒤에_OpenSearch를_고치고_outbox는_쓰지_않는다() throws Exception {
        Integer[] seenByIndex = new Integer[1];
        doAnswer(call -> seenByIndex[0] = price()).when(reviewIndex).updatePrice(productId, 30000);

        changePrice(30000).andExpect(status().isOk());

        verify(reviewIndex).updatePrice(productId, 30000);
        assertThat(seenByIndex[0]).isEqualTo(30000);
        assertThat(jdbcTemplate.queryForObject("SELECT count(*) FROM outbox", Integer.class)).isZero();
    }

    @Test
    void OpenSearch가_실패해도_가격은_바뀐_채로_200을_돌려준다() throws Exception {
        doThrow(new ResourceAccessException("read timed out")).when(reviewIndex).updatePrice(productId, 30000);

        changePrice(30000).andExpect(status().isOk());

        assertThat(price()).isEqualTo(30000);
    }

    private Integer price() {
        return jdbcTemplate.queryForObject("SELECT price FROM products WHERE id = ?", Integer.class, productId);
    }

    private ResultActions changePrice(int price) throws Exception {
        return mockMvc.perform(put("/internal/products/{id}/price", productId)
                .contentType(MediaType.APPLICATION_JSON)
                .content("{\"price\": " + price + "}"));
    }
}
