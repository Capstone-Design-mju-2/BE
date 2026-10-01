package com.capstone.catalog.product;

import java.util.List;

import jakarta.validation.constraints.Max;
import jakarta.validation.constraints.Min;
import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.PositiveOrZero;

import org.springframework.http.HttpStatus;
import org.springframework.web.bind.MissingServletRequestParameterException;
import org.springframework.web.bind.annotation.*;
import org.springframework.web.method.annotation.HandlerMethodValidationException;

import com.capstone.catalog.product.ProductSearch.Product;

@RestController
@RequestMapping("/api/v1/products")
public class ProductSearchController {

    private final ProductSearch productSearch;

    public ProductSearchController(ProductSearch productSearch) {
        this.productSearch = productSearch;
    }

    @GetMapping("/search")
    public SearchResponse search(@RequestParam @NotBlank String q,
                                 @RequestParam(required = false) @PositiveOrZero Integer maxPrice,
                                 @RequestParam(defaultValue = "5") @Min(1) @Max(20) int limit) {
        return new SearchResponse(productSearch.search(q.strip(), maxPrice, limit));
    }

    @ExceptionHandler({MissingServletRequestParameterException.class, HandlerMethodValidationException.class})
    @ResponseStatus(HttpStatus.BAD_REQUEST)
    public ErrorResponse invalidRequest() {
        return new ErrorResponse("INVALID_SEARCH_REQUEST", "q는 필수이고 limit은 1~20, maxPrice는 0 이상이어야 합니다.");
    }

    public record SearchResponse(List<Product> products) {}

    public record ErrorResponse(String code, String message) {}
}
