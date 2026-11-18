package com.capstone.catalog.product;

import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.boot.webmvc.test.autoconfigure.AutoConfigureMockMvc;
import org.springframework.context.annotation.Import;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.test.web.servlet.MockMvc;

import com.capstone.catalog.TestcontainersConfiguration;

import static org.hamcrest.Matchers.anEmptyMap;
import static org.hamcrest.Matchers.contains;
import static org.hamcrest.Matchers.hasSize;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

@SpringBootTest
@AutoConfigureMockMvc
@Import(TestcontainersConfiguration.class)
class ProductSurveyControllerTest {

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
                    VALUES (?, ?, '상품', '브랜드', '104001', 10000, 10000, ?, 100, DATE '2026-09-30')
                    """, id, id * 1000, id * 100);
        }
        review(1, 1, "끈적임 여부", "전혀 없음");
        review(2, 1, "끈적임 여부", "전혀없음 ");
        review(3, 1, "끈적임 여부", "보통");
        review(4, 1, "보습력", "높음");
    }

    void review(long id, long productId, String attribute, String answer) {
        jdbcTemplate.update("""
                INSERT INTO reviews (id, product_id, external_id, content, grade, like_count, written_at, collected_on)
                VALUES (?, ?, ?, '좋아요', 5, 0, TIMESTAMPTZ '2026-09-30 00:00:00+09', DATE '2026-09-30')
                """, id, productId, id);
        jdbcTemplate.update("INSERT INTO review_survey_answers (review_id, attribute, answer) VALUES (?, ?, ?)",
                id, attribute, answer);
    }

    @Test
    void 물은_항목의_답을_띄어쓰기_없이_세고_답이_없는_상품은_빈_값이다() throws Exception {
        mockMvc.perform(get("/internal/products/survey").param("ids", "1", "2", "999")
                        .param("attribute", "끈적임 여부"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.surveys", hasSize(2)))
                .andExpect(jsonPath("$.surveys[?(@.productId == 1)].reviewCount").value(contains(100)))
                .andExpect(jsonPath("$.surveys[?(@.productId == 1)].answers.전혀없음").value(contains(2)))
                .andExpect(jsonPath("$.surveys[?(@.productId == 1)].answers.보통").value(contains(1)))
                .andExpect(jsonPath("$.surveys[?(@.productId == 1)].answers.높음").isEmpty())
                .andExpect(jsonPath("$.surveys[?(@.productId == 2)].answers").value(contains(anEmptyMap())));
    }

    @Test
    void 항목_없이_물으면_리뷰_수만_준다() throws Exception {
        mockMvc.perform(get("/internal/products/survey").param("ids", "2", "1"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.surveys[?(@.productId == 2)].reviewCount").value(contains(200)))
                .andExpect(jsonPath("$.surveys[?(@.productId == 1)].answers").value(contains(anEmptyMap())));
    }
}
