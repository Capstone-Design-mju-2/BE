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

import static org.assertj.core.api.Assertions.assertThat;
import static org.hamcrest.Matchers.everyItem;
import static org.hamcrest.Matchers.greaterThanOrEqualTo;
import static org.hamcrest.Matchers.hasSize;
import static org.hamcrest.Matchers.lessThanOrEqualTo;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

@SpringBootTest
@AutoConfigureMockMvc
@Import(TestcontainersConfiguration.class)
class ProductSearchControllerTest {

    @Autowired
    MockMvc mockMvc;

    @Autowired
    JdbcTemplate jdbcTemplate;

    @BeforeEach
    void seed() {
        jdbcTemplate.update("TRUNCATE products, reviews, review_survey_answers RESTART IDENTITY");
        product(1, "촉촉 토너", 20000);          // q only in the name
        product(2, "세라마이드 크림", 25000);    // q only in reviews, 3 hits
        product(3, "비타민 세럼", 90000);        // q in reviews, over maxPrice
        product(4, "촉촉 미스트", 15000);        // q in the name, no reviews at all
        product(5, "선크림", 18000);             // no match

        review(101, 1, 5, "2026-09-01", "산뜻하고 가벼워요");
        review(102, 1, 3, "2026-09-02", "향이 좀 강해요");
        review(201, 2, 4, "2026-09-10", "아침까지 촉촉해요");
        review(202, 2, 5, "2026-09-05", "건성인데 촉촉하고 당김이 없어요");
        review(203, 2, 5, "2026-09-08", "촉촉함이 오래가요 " + "정말 ".repeat(40));
        review(204, 2, 5, "2026-09-20", "흡수가 빨라요");
        review(301, 3, 5, "2026-09-01", "촉촉해요");
        review(501, 5, 5, "2026-09-01", "백탁이 없어요");
    }

    @Test
    void 상품명에만_있는_상품과_리뷰에만_있는_상품이_모두_들어온다() throws Exception {
        mockMvc.perform(get("/api/v1/products/search").param("q", "촉촉").param("maxPrice", "30000"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.products[*].productId").value(org.hamcrest.Matchers.contains(2, 1)))
                .andExpect(jsonPath("$.products[*].evidence", everyItem(hasSize(greaterThanOrEqualTo(1)))));
    }

    @Test
    void maxPrice를_넘는_상품과_리뷰가_없는_상품은_빠진다() throws Exception {
        mockMvc.perform(get("/api/v1/products/search").param("q", "촉촉").param("maxPrice", "30000"))
                .andExpect(jsonPath("$.products[?(@.productId == 3)]").isEmpty())
                .andExpect(jsonPath("$.products[?(@.productId == 4)]").isEmpty());

        mockMvc.perform(get("/api/v1/products/search").param("q", "촉촉"))
                .andExpect(jsonPath("$.products[?(@.productId == 3)]").isNotEmpty());
    }

    @Test
    void evidence는_q가_걸린_리뷰를_별점_높은_순_동점이면_최신순으로_최대_2개_고른다() throws Exception {
        mockMvc.perform(get("/api/v1/products/search").param("q", "촉촉").param("limit", "1"))
                .andExpect(jsonPath("$.products", hasSize(1)))
                .andExpect(jsonPath("$.products[0].productId").value(2))
                .andExpect(jsonPath("$.products[0].evidence[*].reviewId").value(org.hamcrest.Matchers.contains(203, 202)))
                .andExpect(jsonPath("$.products[0].evidence[*].rating").value(org.hamcrest.Matchers.contains(5, 5)));
    }

    @Test
    void 상품명에만_걸린_상품은_전체_리뷰에서_근거를_고른다() throws Exception {
        mockMvc.perform(get("/api/v1/products/search").param("q", "토너"))
                .andExpect(jsonPath("$.products[0].productId").value(1))
                .andExpect(jsonPath("$.products[0].evidence[*].reviewId").value(org.hamcrest.Matchers.contains(101, 102)));
    }

    @Test
    void excerpt는_80자를_넘지_않고_q_주변을_보여준다() throws Exception {
        mockMvc.perform(get("/api/v1/products/search").param("q", "촉촉"))
                .andExpect(jsonPath("$.products[*].evidence[*].excerpt",
                        everyItem(org.hamcrest.Matchers.hasToString(
                                org.hamcrest.Matchers.matchesPattern("(?s).{1,80}")))));

        String longText = "가".repeat(100) + "촉촉해요" + "나".repeat(100);
        String excerpt = ProductSearch.excerpt(longText, "촉촉");
        assertThat(excerpt.codePointCount(0, excerpt.length())).isEqualTo(80);
        assertThat(excerpt).contains("촉촉");

        String english = "가".repeat(100) + "SPF50 선크림" + "나".repeat(100);
        assertThat(ProductSearch.excerpt(english, "spf")).contains("SPF50");
    }

    @Test
    void limit보다_많이_반환하지_않고_잘못된_요청은_400이다() throws Exception {
        mockMvc.perform(get("/api/v1/products/search").param("q", "요").param("limit", "2"))
                .andExpect(jsonPath("$.products", hasSize(lessThanOrEqualTo(2))));

        mockMvc.perform(get("/api/v1/products/search").param("q", "촉촉").param("limit", "21"))
                .andExpect(status().isBadRequest())
                .andExpect(jsonPath("$.code").value("INVALID_SEARCH_REQUEST"));
        mockMvc.perform(get("/api/v1/products/search"))
                .andExpect(status().isBadRequest());
        mockMvc.perform(get("/api/v1/products/search").param("q", " "))
                .andExpect(status().isBadRequest());
        mockMvc.perform(get("/api/v1/products/search").param("q", "촉촉").param("maxPrice", "abc"))
                .andExpect(status().isBadRequest())
                .andExpect(jsonPath("$.code").value("INVALID_SEARCH_REQUEST"));
    }

    @Test
    void 퍼센트와_밑줄은_와일드카드가_아니라_글자로_찾는다() throws Exception {
        mockMvc.perform(get("/api/v1/products/search").param("q", "%"))
                .andExpect(jsonPath("$.products").isEmpty());
    }

    private void product(long id, String name, int price) {
        jdbcTemplate.update("""
                INSERT INTO products (id, external_id, name, brand_name, category_code, normal_price, price,
                                      review_count, review_score, collected_on)
                VALUES (?, ?, ?, '브랜드', '104001', ?, ?, 10, 90, DATE '2026-09-30')
                """, id, id * 1000, name, price, price);
    }

    private void review(long id, long productId, int grade, String date, String content) {
        jdbcTemplate.update("""
                INSERT INTO reviews (id, product_id, external_id, content, grade, like_count, written_at, collected_on)
                VALUES (?, ?, ?, ?, ?, 0, CAST(? AS date), DATE '2026-09-30')
                """, id, productId, id * 1000, content, grade, date);
    }
}
