package com.capstone.catalog.product;

import java.time.LocalDate;
import java.time.OffsetDateTime;
import java.util.List;

import jakarta.validation.Valid;
import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.NotNull;

import org.springframework.web.bind.annotation.*;

@RestController
@RequestMapping("/internal/products")
public class ProductLoadController {

    private final ProductLoader productLoader;

    public ProductLoadController(ProductLoader productLoader) {
        this.productLoader = productLoader;
    }

    @PostMapping("/load")
    public LoadResponse load(@Valid @RequestBody LoadProductRequest request) {
        return new LoadResponse(productLoader.load(request), request.reviews().size());
    }

    public record LoadResponse(long productId, int reviewCount) {}

    public record LoadProductRequest(
            @NotNull Long externalId,
            @NotBlank String name,
            @NotBlank String brandName,
            @NotBlank String categoryCode,
            @NotNull Integer normalPrice,
            @NotNull Integer price,
            @NotNull Integer reviewCount,
            @NotNull Integer reviewScore,
            @NotNull LocalDate collectedOn,
            @NotNull List<@Valid @NotNull Review> reviews) {}

    public record Review(
            @NotNull Long externalId,
            @NotNull String content,
            @NotNull Integer grade,
            int likeCount,
            String optionText,
            String skinType,
            String skinTone,
            String gender,
            Integer heightMinCm,
            Integer heightMaxCm,
            Integer weightMinKg,
            Integer weightMaxKg,
            @NotNull OffsetDateTime writtenAt,
            Survey survey,
            @NotNull LocalDate collectedOn) {}

    public record Survey(List<Question> questions) {}

    public record Question(String attribute, List<Answer> answers) {}

    public record Answer(String answerShortText) {}
}
