package com.capstone.catalog.product;

import java.util.List;

import jakarta.validation.constraints.Size;

import org.springframework.web.bind.annotation.*;

/** Image addresses for search-mcp's OpenSearch path: the review index has none (ADR-151). */
@RestController
@RequestMapping("/internal/products")
public class ProductImageController {

    private final ProductList productList;

    public ProductImageController(ProductList productList) {
        this.productList = productList;
    }

    @GetMapping("/images")
    public ImagesResponse images(@RequestParam @Size(min = 1, max = 20) List<Long> ids) {
        return new ImagesResponse(productList.images(ids));
    }

    public record ImagesResponse(List<ProductList.Image> images) {}
}
