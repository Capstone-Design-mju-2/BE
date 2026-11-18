package com.capstone.catalog.product;

import java.util.HashMap;
import java.util.List;
import java.util.Map;
import java.util.TreeMap;

import jakarta.validation.constraints.Size;

import org.springframework.jdbc.core.RowCallbackHandler;
import org.springframework.jdbc.core.namedparam.NamedParameterJdbcTemplate;
import org.springframework.web.bind.annotation.*;

/** What search-mcp ranks found products by: buyers' survey answers on one item, and the review count (ADR-177). */
@RestController
@RequestMapping("/internal/products")
public class ProductSurveyController {

    private static final String COUNTS = "SELECT id, review_count FROM products WHERE id IN (:ids)";
    // Musinsa wrote the same answer with and without spaces ("전혀 없음", "전혀없음 "), so spaces are dropped.
    private static final String ANSWERS = """
            SELECT r.product_id, replace(s.answer, ' ', '') AS answer, count(*) AS answers
            FROM review_survey_answers s JOIN reviews r ON r.id = s.review_id
            WHERE s.attribute = :attribute AND r.product_id IN (:ids)
            GROUP BY r.product_id, replace(s.answer, ' ', '')
            """;

    private final NamedParameterJdbcTemplate jdbcTemplate;

    public ProductSurveyController(NamedParameterJdbcTemplate jdbcTemplate) {
        this.jdbcTemplate = jdbcTemplate;
    }

    @GetMapping("/survey")
    public SurveyResponse survey(@RequestParam @Size(min = 1, max = 20) List<Long> ids,
                                 @RequestParam(required = false) String attribute) {
        Map<Long, Map<String, Integer>> answers = new HashMap<>();
        if (attribute != null) {
            jdbcTemplate.query(ANSWERS, Map.of("ids", ids, "attribute", attribute), (RowCallbackHandler) rs ->
                    answers.computeIfAbsent(rs.getLong("product_id"), id -> new TreeMap<>())
                            .put(rs.getString("answer"), rs.getInt("answers")));
        }
        return new SurveyResponse(jdbcTemplate.query(COUNTS, Map.of("ids", ids), (rs, row) -> new Survey(
                rs.getLong("id"), rs.getInt("review_count"), answers.getOrDefault(rs.getLong("id"), Map.of()))));
    }

    public record SurveyResponse(List<Survey> surveys) {}

    /** answers maps each answer of the asked item to how many buyers gave it; empty without an item or answers. */
    public record Survey(long productId, int reviewCount, Map<String, Integer> answers) {}
}
