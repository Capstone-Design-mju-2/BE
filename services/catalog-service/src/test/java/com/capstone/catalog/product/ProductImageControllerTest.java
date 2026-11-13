package com.capstone.catalog.product;

import java.util.Collections;

import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.boot.webmvc.test.autoconfigure.AutoConfigureMockMvc;
import org.springframework.context.annotation.Import;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.test.web.servlet.MockMvc;

import com.capstone.catalog.TestcontainersConfiguration;

import static org.hamcrest.Matchers.contains;
import static org.hamcrest.Matchers.hasSize;
import static org.hamcrest.Matchers.nullValue;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

@SpringBootTest
@AutoConfigureMockMvc
@Import(TestcontainersConfiguration.class)
class ProductImageControllerTest {

    static final String URL = "https://image.msscdn.net/images/goods_img/20260930/2000/2000_1_500.jpg";

    @Autowired
    MockMvc mockMvc;

    @Autowired
    JdbcTemplate jdbcTemplate;

    @BeforeEach
    void seed() {
        jdbcTemplate.update("TRUNCATE products, reviews, review_survey_answers, product_ingredients RESTART IDENTITY");
        for (long id = 1; id <= 2; id++) {
            jdbcTemplate.update("""
                    INSERT INTO products (id, external_id, name, brand_name, category_code, normal_price, price,
                                          review_count, review_score, collected_on)
                    VALUES (?, ?, '상품', '브랜드', '104001', 10000, 10000, 1, 100, DATE '2026-09-30')
                    """, id, id * 1000);
        }
        jdbcTemplate.update("UPDATE products SET image_url = ? WHERE id = 2", URL);
    }

    @Test
    void 있는_상품만_사진_주소를_주고_사진이_없으면_null이다() throws Exception {
        mockMvc.perform(get("/internal/products/images").param("ids", "2", "1", "999"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.images", hasSize(2)))
                .andExpect(jsonPath("$.images[?(@.productId == 2)].imageUrl").value(URL))
                .andExpect(jsonPath("$.images[?(@.productId == 2)].thumbnailUrl")
                        .value(URL.replace("_500.jpg", "_125.jpg")))
                .andExpect(jsonPath("$.images[?(@.productId == 1)].imageUrl").value(contains(nullValue())));
    }

    @Test
    void 번호가_없거나_20개를_넘으면_400이다() throws Exception {
        mockMvc.perform(get("/internal/products/images"))
                .andExpect(status().isBadRequest());
        mockMvc.perform(get("/internal/products/images").param("ids", "abc"))
                .andExpect(status().isBadRequest());
        mockMvc.perform(get("/internal/products/images")
                        .param("ids", Collections.nCopies(21, "1").toArray(String[]::new)))
                .andExpect(status().isBadRequest());
    }
}
