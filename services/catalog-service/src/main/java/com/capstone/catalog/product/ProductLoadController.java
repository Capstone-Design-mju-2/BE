package com.capstone.catalog.product;

import java.time.LocalDate;
import java.time.OffsetDateTime;
import java.util.List;

import jakarta.validation.Valid;
import jakarta.validation.constraints.AssertTrue;
import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.NotNull;
import jakarta.validation.constraints.Pattern;
import jakarta.validation.constraints.Size;

import org.springframework.http.ResponseEntity;
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

    @PutMapping("/{externalId}/ingredients")
    public ResponseEntity<Void> loadIngredients(@PathVariable long externalId,
                                                @Valid @RequestBody IngredientsRequest request) {
        return productLoader.loadIngredients(externalId, request.names(), request.source(), request.sourceUrl())
                ? ResponseEntity.noContent().build()
                : ResponseEntity.notFound().build();
    }

    public record LoadResponse(long productId, int reviewCount) {}

    /** An empty names list marks the product's ingredients as unknown; source is then ignored. */
    public record IngredientsRequest(
            @NotNull List<@NotBlank @Size(max = 100) String> names,
            @Pattern(regexp = "musinsa|glowpick") String source,
            @Size(max = 200) String sourceUrl) {

        @AssertTrue
        boolean isSourceGivenForNames() {
            return names == null || names.isEmpty() || source != null;
        }
    }

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
