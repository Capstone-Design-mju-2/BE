package com.capstone.catalog.product;

import java.util.List;

import jakarta.validation.constraints.Max;
import jakarta.validation.constraints.Min;
import jakarta.validation.constraints.Pattern;

import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.MissingServletRequestParameterException;
import org.springframework.web.bind.annotation.*;
import org.springframework.web.method.annotation.HandlerMethodValidationException;
import org.springframework.web.method.annotation.MethodArgumentTypeMismatchException;

import com.capstone.catalog.product.ProductList.Product;

@RestController
@RequestMapping("/api/v1/products")
public class ProductListController {

    private static final ErrorResponse INVALID = new ErrorResponse("INVALID_PRODUCT_LIST",
            "category는 있는 6자리 코드이고 sort는 popular·rating·priceAsc·priceDesc, page는 0 이상, size는 1~50이어야 합니다.");

    private final ProductList productList;

    public ProductListController(ProductList productList) {
        this.productList = productList;
    }

    @GetMapping
    public ResponseEntity<?> list(@RequestParam @Pattern(regexp = "\\d{6}") String category,
                                  @RequestParam(defaultValue = "popular")
                                  @Pattern(regexp = "popular|rating|priceAsc|priceDesc") String sort,
                                  @RequestParam(defaultValue = "0") @Min(0) int page,
                                  @RequestParam(defaultValue = "20") @Min(1) @Max(50) int size) {
        var found = productList.list(category, sort, page, size);
        if (found == null) {
            return ResponseEntity.badRequest().body(INVALID);
        }
        return ResponseEntity.ok(new ListResponse(category, page, size, found.total(), found.products()));
    }

    @ExceptionHandler({MissingServletRequestParameterException.class, HandlerMethodValidationException.class,
            MethodArgumentTypeMismatchException.class})
    @ResponseStatus(HttpStatus.BAD_REQUEST)
    public ErrorResponse invalidRequest() {
        return INVALID;
    }

    public record ListResponse(String category, int page, int size, long total, List<Product> products) {}

    public record ErrorResponse(String code, String message) {}
}
