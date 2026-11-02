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

import com.capstone.catalog.product.ReviewList.Review;

@RestController
@RequestMapping("/api/v1/products")
public class ReviewListController {

    private final ReviewList reviewList;

    public ReviewListController(ReviewList reviewList) {
        this.reviewList = reviewList;
    }

    @GetMapping("/{productId}/reviews")
    public ResponseEntity<?> list(@PathVariable long productId,
                                  @RequestParam(defaultValue = "recent") @Pattern(regexp = "recent|rating|likes") String sort,
                                  @RequestParam(required = false)
                                  @Pattern(regexp = "dry|oily|combination|sensitive") String skinType,
                                  @RequestParam(defaultValue = "0") @Min(0) int page,
                                  @RequestParam(defaultValue = "20") @Min(1) @Max(50) int size) {
        var found = reviewList.list(productId, skinType, sort, page, size);
        if (found == null) {
            return ResponseEntity.status(HttpStatus.NOT_FOUND)
                    .body(new ErrorResponse("PRODUCT_NOT_FOUND", "상품이 없습니다."));
        }
        return ResponseEntity.ok(new ListResponse(productId, page, size, found.total(), found.reviews()));
    }

    @ExceptionHandler({MissingServletRequestParameterException.class, HandlerMethodValidationException.class,
            MethodArgumentTypeMismatchException.class})
    @ResponseStatus(HttpStatus.BAD_REQUEST)
    public ErrorResponse invalidRequest() {
        return new ErrorResponse("INVALID_REVIEW_LIST",
                "sort는 recent·rating·likes, skinType은 dry·oily·combination·sensitive, page는 0 이상, size는 1~50이어야 합니다.");
    }

    public record ListResponse(long productId, int page, int size, long total, List<Review> reviews) {}

    public record ErrorResponse(String code, String message) {}
}
