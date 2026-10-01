package com.capstone.catalog.product;

import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.boot.webmvc.test.autoconfigure.AutoConfigureMockMvc;
import org.springframework.context.annotation.Import;
import org.springframework.http.MediaType;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.test.web.servlet.MockMvc;

import com.capstone.catalog.TestcontainersConfiguration;

import static org.assertj.core.api.Assertions.assertThat;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

@SpringBootTest
@AutoConfigureMockMvc
@Import(TestcontainersConfiguration.class)
class ProductLoadControllerTest {

    private static final String PRODUCT = """
            {"externalId": 5816625, "name": "세라마이드 모이스처라이저", "brandName": "코스알엑스",
             "categoryCode": "104001", "normalPrice": 50000, "price": %d, "reviewCount": 245,
             "reviewScore": 98, "isSoldOut": false, "collectedOn": "2026-09-30",
             "reviews": [
               {"externalId": 1, "content": "%s", "grade": 5, "likeCount": 3, "optionText": null,
                "skinType": "dry", "skinTone": "spring_warm", "gender": null,
                "heightMinCm": 160, "heightMaxCm": 165, "weightMinKg": null, "weightMaxKg": null,
                "writtenAt": "2026-09-29T18:08:37.000+09:00", "collectedOn": "2026-09-30",
                "survey": {"surveyKind": "SATISFACTION", "questions": [
                  {"questionId": 25, "attribute": "보습력", "answers": [{"answerId": 121, "answerShortText": "매우 높음"}]},
                  {"questionId": 27, "attribute": "자극여부", "answers": [{"answerId": 131, "answerShortText": "전혀없음"}]}]}},
               {"externalId": 2, "content": "흡수가 빨라요", "grade": 4, "likeCount": 0, "optionText": "50ml",
                "skinType": null, "skinTone": null, "gender": null,
                "heightMinCm": null, "heightMaxCm": null, "weightMinKg": null, "weightMaxKg": null,
                "writtenAt": "2026-09-28T10:00:00.000+09:00", "collectedOn": "2026-09-30", "survey": null}
             ]}
            """;

    @Autowired
    MockMvc mockMvc;

    @Autowired
    JdbcTemplate jdbcTemplate;

    @BeforeEach
    void clean() {
        jdbcTemplate.update("TRUNCATE products, reviews, review_survey_answers RESTART IDENTITY");
    }

    @Test
    void 같은_상품을_두_번_적재해도_행이_늘지_않는다() throws Exception {
        String body = PRODUCT.formatted(40000, "촉촉해요");

        load(body);
        load(body);

        assertThat(count("products")).isEqualTo(1);
        assertThat(count("reviews")).isEqualTo(2);
        assertThat(count("review_survey_answers")).isEqualTo(2);
    }

    @Test
    void 재수집에서_빠진_리뷰는_설문_답변이_남는다() throws Exception {
        load(PRODUCT.formatted(40000, "촉촉해요"));
        String onlySecondReview = PRODUCT.formatted(40000, "촉촉해요")
                .replaceAll("(?s)\\{\"externalId\": 1,.*?\"전혀없음\"}]}]}},", "");

        mockMvc.perform(post("/api/v1/products/load").contentType(MediaType.APPLICATION_JSON).content(onlySecondReview))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.reviewCount").value(1));

        assertThat(count("reviews")).isEqualTo(2);
        assertThat(count("review_survey_answers")).isEqualTo(2);
    }

    @Test
    void 다시_적재하면_가격과_리뷰_본문이_새_값으로_바뀐다() throws Exception {
        load(PRODUCT.formatted(40000, "촉촉해요"));
        load(PRODUCT.formatted(35000, "겨울에도 촉촉해요"));

        assertThat(jdbcTemplate.queryForObject("SELECT price FROM products", Integer.class)).isEqualTo(35000);
        assertThat(jdbcTemplate.queryForObject("SELECT content FROM reviews WHERE external_id = 1", String.class))
                .isEqualTo("겨울에도 촉촉해요");
    }

    @Test
    void 필수_값이_없으면_400을_반환한다() throws Exception {
        mockMvc.perform(post("/api/v1/products/load")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content("{\"externalId\": 1}"))
                .andExpect(status().isBadRequest());
    }

    private void load(String body) throws Exception {
        mockMvc.perform(post("/api/v1/products/load").contentType(MediaType.APPLICATION_JSON).content(body))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.reviewCount").value(2));
    }

    private int count(String table) {
        return jdbcTemplate.queryForObject("SELECT count(*) FROM " + table, Integer.class);
    }
}
