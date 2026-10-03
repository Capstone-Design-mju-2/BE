package com.capstone.catalog.product;

import java.util.ArrayList;
import java.util.List;

import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Repository;
import org.springframework.transaction.annotation.Transactional;

import com.capstone.catalog.product.ProductLoadController.LoadProductRequest;
import com.capstone.catalog.product.ProductLoadController.Review;

@Repository
public class ProductLoader {

    private static final String UPSERT_PRODUCT = """
            INSERT INTO products (external_id, name, brand_name, category_code, normal_price, price,
                                  review_count, review_score, collected_on)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT (external_id) DO UPDATE SET
                name = EXCLUDED.name, brand_name = EXCLUDED.brand_name, category_code = EXCLUDED.category_code,
                normal_price = EXCLUDED.normal_price, price = EXCLUDED.price, review_count = EXCLUDED.review_count,
                review_score = EXCLUDED.review_score, collected_on = EXCLUDED.collected_on
            RETURNING id
            """;

    private static final String UPSERT_REVIEW = """
            INSERT INTO reviews (product_id, external_id, content, grade, like_count, option_text, skin_type,
                                 skin_tone, gender, height_min_cm, height_max_cm, weight_min_kg, weight_max_kg,
                                 written_at, collected_on)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT (external_id) DO UPDATE SET
                product_id = EXCLUDED.product_id, content = EXCLUDED.content, grade = EXCLUDED.grade,
                like_count = EXCLUDED.like_count, option_text = EXCLUDED.option_text,
                skin_type = EXCLUDED.skin_type, skin_tone = EXCLUDED.skin_tone, gender = EXCLUDED.gender,
                height_min_cm = EXCLUDED.height_min_cm, height_max_cm = EXCLUDED.height_max_cm,
                weight_min_kg = EXCLUDED.weight_min_kg, weight_max_kg = EXCLUDED.weight_max_kg,
                written_at = EXCLUDED.written_at, collected_on = EXCLUDED.collected_on
            """;

    // Only reviews in this payload: a review missing from a recollection keeps its answers.
    private static final String DELETE_SURVEY_ANSWERS = """
            DELETE FROM review_survey_answers
            WHERE review_id = (SELECT id FROM reviews WHERE external_id = ?)
            """;

    private static final String INSERT_SURVEY_ANSWER = """
            INSERT INTO review_survey_answers (review_id, attribute, answer)
            SELECT id, ?, ? FROM reviews WHERE external_id = ?
            ON CONFLICT DO NOTHING
            """;

    private final JdbcTemplate jdbcTemplate;

    public ProductLoader(JdbcTemplate jdbcTemplate) {
        this.jdbcTemplate = jdbcTemplate;
    }

    @Transactional
    public long load(LoadProductRequest p) {
        long productId = jdbcTemplate.queryForObject(UPSERT_PRODUCT, Long.class,
                p.externalId(), p.name(), p.brandName(), p.categoryCode(), p.normalPrice(), p.price(),
                p.reviewCount(), p.reviewScore(), p.collectedOn());

        jdbcTemplate.batchUpdate(UPSERT_REVIEW, p.reviews().stream()
                .map(r -> new Object[] {productId, r.externalId(), r.content(), r.grade(), r.likeCount(),
                        r.optionText(), r.skinType(), r.skinTone(), r.gender(), r.heightMinCm(), r.heightMaxCm(),
                        r.weightMinKg(), r.weightMaxKg(), r.writtenAt(), r.collectedOn()})
                .toList());

        jdbcTemplate.batchUpdate(DELETE_SURVEY_ANSWERS, p.reviews().stream()
                .map(r -> new Object[] {r.externalId()})
                .toList());
        jdbcTemplate.batchUpdate(INSERT_SURVEY_ANSWER, surveyAnswers(p.reviews()));
        return productId;
    }

    private static List<Object[]> surveyAnswers(List<Review> reviews) {
        var rows = new ArrayList<Object[]>();
        for (var review : reviews) {
            if (review.survey() == null || review.survey().questions() == null) {
                continue;
            }
            for (var question : review.survey().questions()) {
                if (question.answers() == null) {
                    continue;
                }
                for (var answer : question.answers()) {
                    rows.add(new Object[] {question.attribute(), answer.answerShortText(), review.externalId()});
                }
            }
        }
        return rows;
    }
}
