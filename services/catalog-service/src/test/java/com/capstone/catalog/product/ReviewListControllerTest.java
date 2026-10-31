package com.capstone.catalog.product;

import java.util.List;
import java.util.Map;

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
import static org.hamcrest.Matchers.nullValue;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

@SpringBootTest
@AutoConfigureMockMvc
@Import(TestcontainersConfiguration.class)
class ReviewListControllerTest {

    static final String LONG_CONTENT = "정말 ".repeat(40) + "촉촉해요";

    @Autowired
    MockMvc mockMvc;

    @Autowired
    JdbcTemplate jdbcTemplate;

    @BeforeEach
    void seed() {
        jdbcTemplate.update("TRUNCATE products, reviews, review_survey_answers, product_ingredients RESTART IDENTITY");
        product(1);
        product(2); // no reviews
        product(3);
        // 20:00 UTC on 8/31 is already 9/1 in Korea.
        review(11, 1, 5, 20, "dry", "50ml", "2026-08-31T20:00:00Z", LONG_CONTENT);
        review(12, 1, 3, 10, null, null, "2026-09-02T01:00:00Z", "향이 좀 강해요");
        review(13, 1, 5, 10, "oily", "50ml", "2026-09-02T01:00:00Z", "산뜻해요"); // same time as 12
        review(14, 1, 1, 0, "dry", "100ml", "2026-08-01T00:00:00Z", "따가워요");
        review(31, 3, 5, 0, "dry", null, "2026-09-01T00:00:00Z", "다른 상품 리뷰");
    }

    @Test
    void 기본은_최신순이고_같은_시각이면_리뷰_번호가_큰_순이다() throws Exception {
        mockMvc.perform(get("/api/v1/products/1/reviews"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.productId").value(1))
                .andExpect(jsonPath("$.page").value(0))
                .andExpect(jsonPath("$.size").value(20))
                .andExpect(jsonPath("$.total").value(4))
                .andExpect(jsonPath("$.reviews[*].reviewId").value(contains(13, 12, 11, 14)))
                .andExpect(jsonPath("$.reviews[1].skinType").value(nullValue()))
                .andExpect(jsonPath("$.reviews[1].optionText").value(nullValue()));
    }

    @Test
    void 리뷰_본문은_자르지_않고_작성일은_한국_날짜로_준다() throws Exception {
        mockMvc.perform(get("/api/v1/products/1/reviews").param("sort", "likes"))
                .andExpect(jsonPath("$.reviews[0].reviewId").value(11))
                .andExpect(jsonPath("$.reviews[0].rating").value(5))
                .andExpect(jsonPath("$.reviews[0].content").value(LONG_CONTENT))
                .andExpect(jsonPath("$.reviews[0].skinType").value("dry"))
                .andExpect(jsonPath("$.reviews[0].optionText").value("50ml"))
                .andExpect(jsonPath("$.reviews[0].likeCount").value(20))
                .andExpect(jsonPath("$.reviews[0].writtenAt").value("2026-09-01"));
    }

    @Test
    void 별점순과_좋아요순은_같은_값이면_최신순으로_잇는다() throws Exception {
        mockMvc.perform(get("/api/v1/products/1/reviews").param("sort", "rating"))
                .andExpect(jsonPath("$.reviews[*].reviewId").value(contains(13, 11, 12, 14)));
        mockMvc.perform(get("/api/v1/products/1/reviews").param("sort", "likes"))
                .andExpect(jsonPath("$.reviews[*].reviewId").value(contains(11, 13, 12, 14)));
    }

    @Test
    void skinType을_주면_그_피부_타입_리뷰만_준다() throws Exception {
        mockMvc.perform(get("/api/v1/products/1/reviews").param("skinType", "dry"))
                .andExpect(jsonPath("$.total").value(2))
                .andExpect(jsonPath("$.reviews[*].reviewId").value(contains(11, 14)));
        mockMvc.perform(get("/api/v1/products/1/reviews").param("skinType", "sensitive"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.total").value(0))
                .andExpect(jsonPath("$.reviews").isEmpty());
    }

    @Test
    void 쪽끼리_겹치지_않고_마지막_쪽을_넘으면_빈_목록이다() throws Exception {
        mockMvc.perform(get("/api/v1/products/1/reviews").param("size", "2"))
                .andExpect(jsonPath("$.reviews[*].reviewId").value(contains(13, 12)));
        mockMvc.perform(get("/api/v1/products/1/reviews").param("size", "2").param("page", "1"))
                .andExpect(jsonPath("$.reviews[*].reviewId").value(contains(11, 14)));
        mockMvc.perform(get("/api/v1/products/1/reviews").param("size", "2").param("page", "2"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.reviews").isEmpty())
                .andExpect(jsonPath("$.total").value(4));
    }

    @Test
    void 리뷰가_없는_상품은_빈_목록이고_없는_상품은_404다() throws Exception {
        mockMvc.perform(get("/api/v1/products/2/reviews"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.total").value(0))
                .andExpect(jsonPath("$.reviews").isEmpty());
        mockMvc.perform(get("/api/v1/products/999/reviews"))
                .andExpect(status().isNotFound())
                .andExpect(jsonPath("$.code").value("PRODUCT_NOT_FOUND"));
    }

    @Test
    void 범위를_벗어난_값은_400이다() throws Exception {
        for (Map<String, String> params : List.of(
                Map.of("sort", "best"),
                Map.of("skinType", "normal"),
                Map.of("skinType", ""),
                Map.of("page", "-1"),
                Map.of("size", "0"),
                Map.of("size", "51"))) {
            var request = get("/api/v1/products/1/reviews");
            params.forEach((name, value) -> request.param(name, value));
            mockMvc.perform(request)
                    .andExpect(status().isBadRequest())
                    .andExpect(jsonPath("$.code").value("INVALID_REVIEW_LIST"));
        }
        mockMvc.perform(get("/api/v1/products/abc/reviews"))
                .andExpect(status().isBadRequest())
                .andExpect(jsonPath("$.code").value("INVALID_REVIEW_LIST"));
    }

    private void product(long id) {
        jdbcTemplate.update("""
                INSERT INTO products (id, external_id, name, brand_name, category_code, normal_price, price,
                                      review_count, review_score, collected_on)
                VALUES (?, ?, ?, '브랜드', '104001', 20000, 20000, 10, 90, DATE '2026-09-30')
                """, id, id * 1000, "상품 " + id);
    }

    private void review(long id, long productId, int grade, int likes, String skinType, String optionText,
                        String writtenAt, String content) {
        jdbcTemplate.update("""
                INSERT INTO reviews (id, product_id, external_id, content, grade, like_count, option_text, skin_type,
                                     written_at, collected_on)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, CAST(? AS timestamptz), DATE '2026-09-30')
                """, id, productId, id * 1000, content, grade, likes, optionText, skinType, writtenAt);
    }
}
