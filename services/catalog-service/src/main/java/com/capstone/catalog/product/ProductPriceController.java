package com.capstone.catalog.product;

import jakarta.validation.Valid;
import jakarta.validation.constraints.Max;
import jakarta.validation.constraints.Min;
import jakarta.validation.constraints.NotNull;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.*;

/**
 * Price changes for the sync experiment (ADR-121). Collected prices are otherwise fixed at the collection date, so
 * nothing else changes a product after loading.
 */
@RestController
@RequestMapping("/internal/products")
public class ProductPriceController {

    private static final Logger log = LoggerFactory.getLogger(ProductPriceController.class);

    private final PriceChanger priceChanger;
    private final ReviewIndex reviewIndex;
    private final IndexSync indexSync;

    public ProductPriceController(PriceChanger priceChanger, ReviewIndex reviewIndex,
                                  @Value("${catalog.index-sync}") String indexSync) {
        this.priceChanger = priceChanger;
        this.reviewIndex = reviewIndex;
        this.indexSync = IndexSync.of(indexSync);
    }

    @PutMapping("/{productId}/price")
    public ResponseEntity<PriceResponse> changePrice(@PathVariable long productId,
                                                     @Valid @RequestBody PriceRequest request) {
        if (!priceChanger.change(productId, request.price(), indexSync == IndexSync.OUTBOX)) {
            return ResponseEntity.notFound().build();
        }
        if (indexSync == IndexSync.DUAL_WRITE) {
            // The price is already committed, so a failure here leaves the index behind. The experiment counts these.
            try {
                reviewIndex.updatePrice(productId, request.price());
            } catch (RuntimeException e) {
                log.warn("Review index kept the old price of product {}", productId, e);
            }
        }
        return ResponseEntity.ok(new PriceResponse(productId, request.price()));
    }

    public record PriceRequest(@NotNull @Min(0) @Max(100_000_000) Integer price) {}

    public record PriceResponse(long productId, int price) {}

    enum IndexSync {
        NONE, DUAL_WRITE, OUTBOX;

        static IndexSync of(String value) {
            return switch (value) {
                case "none" -> NONE;
                case "dual-write" -> DUAL_WRITE;
                case "outbox" -> OUTBOX;
                default -> throw new IllegalArgumentException("unknown catalog.index-sync: " + value);
            };
        }
    }
}
