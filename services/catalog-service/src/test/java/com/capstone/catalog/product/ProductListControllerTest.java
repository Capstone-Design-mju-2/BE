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
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

@SpringBootTest
@AutoConfigureMockMvc
@Import(TestcontainersConfiguration.class)
class ProductListControllerTest {

    @Autowired
    MockMvc mockMvc;

    @Autowired
    JdbcTemplate jdbcTemplate;

    @BeforeEach
    void seed() {
        jdbcTemplate.update("TRUNCATE products, reviews, review_survey_answers, product_ingredients RESTART IDENTITY");
        product(1, "104001", 20000, 500, 90);
        product(2, "104001", 15000, 900, 95);
        product(3, "104001", 30000, 500, 98);   // ties 1 on review count
        product(4, "104001", 15000, 100, 98);   // ties 2 on price and 3 on score
        product(5, "104002", 10000, 9999, 100); // another category
    }

    @Test
    void 기본은_리뷰_수_많은_순이고_같으면_상품_번호_순이다() throws Exception {
        mockMvc.perform(get("/api/v1/products").param("category", "104001"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.category").value("104001"))
                .andExpect(jsonPath("$.page").value(0))
                .andExpect(jsonPath("$.size").value(20))
                .andExpect(jsonPath("$.total").value(4))
                .andExpect(jsonPath("$.products[*].productId").value(contains(2, 1, 3, 4)))
                .andExpect(jsonPath("$.products[0].name").value("상품 2"))
                .andExpect(jsonPath("$.products[0].brand").value("브랜드"))
                .andExpect(jsonPath("$.products[0].price").value(15000))
                .andExpect(jsonPath("$.products[0].reviewCount").value(900))
                .andExpect(jsonPath("$.products[0].reviewScore").value(95));
    }

    @Test
    void 평점순과_가격순도_같은_값이면_상품_번호_순이다() throws Exception {
        expectOrder("rating", 3, 4, 2, 1);
        expectOrder("priceAsc", 2, 4, 1, 3);
        expectOrder("priceDesc", 3, 1, 2, 4);
    }

    @Test
    void 쪽끼리_겹치지_않고_마지막_쪽을_넘으면_빈_목록이다() throws Exception {
        mockMvc.perform(get("/api/v1/products").param("category", "104001").param("size", "3"))
                .andExpect(jsonPath("$.products[*].productId").value(contains(2, 1, 3)));
        mockMvc.perform(get("/api/v1/products").param("category", "104001").param("size", "3").param("page", "1"))
                .andExpect(jsonPath("$.products[*].productId").value(contains(4)))
                .andExpect(jsonPath("$.total").value(4));
        mockMvc.perform(get("/api/v1/products").param("category", "104001").param("size", "3").param("page", "2"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.products").isEmpty())
                .andExpect(jsonPath("$.total").value(4));
        mockMvc.perform(get("/api/v1/products").param("category", "104001").param("size", "50"))
                .andExpect(status().isOk());
    }

    @Test
    void 없는_카테고리와_범위를_벗어난_값은_400이다() throws Exception {
        for (Map<String, String> params : List.of(
                Map.of("sort", "popular"),
                Map.of("category", "스킨케어"),
                Map.of("category", "999999"),
                Map.of("category", "104001", "sort", "cheap"),
                Map.of("category", "104001", "page", "-1"),
                Map.of("category", "104001", "page", "abc"),
                Map.of("category", "104001", "size", "0"),
                Map.of("category", "104001", "size", "51"))) {
            var request = get("/api/v1/products");
            params.forEach((name, value) -> request.param(name, value));
            mockMvc.perform(request)
                    .andExpect(status().isBadRequest())
                    .andExpect(jsonPath("$.code").value("INVALID_PRODUCT_LIST"));
        }
    }

    private void expectOrder(String sort, Integer... productIds) throws Exception {
        mockMvc.perform(get("/api/v1/products").param("category", "104001").param("sort", sort))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.products[*].productId").value(contains(productIds)));
    }

    private void product(long id, String category, int price, int reviewCount, int reviewScore) {
        jdbcTemplate.update("""
                INSERT INTO products (id, external_id, name, brand_name, category_code, normal_price, price,
                                      review_count, review_score, collected_on)
                VALUES (?, ?, ?, '브랜드', ?, ?, ?, ?, ?, DATE '2026-09-30')
                """, id, id * 1000, "상품 " + id, category, price, price, reviewCount, reviewScore);
    }
}
