package com.capstone.order.inventory;

import java.util.List;

import jakarta.validation.Valid;
import jakarta.validation.constraints.NotNull;
import jakarta.validation.constraints.Size;

import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.MethodArgumentNotValidException;
import org.springframework.web.bind.annotation.*;

import com.capstone.order.inventory.InventoryService.InventoryCheck;
import com.capstone.order.inventory.InventoryService.OptionView;

@RestController
@RequestMapping("/api/v1/inventories")
public class InventoryCheckController {

    private final InventoryService inventoryService;

    public InventoryCheckController(InventoryService inventoryService) {
        this.inventoryService = inventoryService;
    }

    @PostMapping("/check")
    public CheckResponse check(@Valid @RequestBody CheckRequest request) {
        return new CheckResponse(inventoryService.check(request.productIds()));
    }

    @GetMapping("/{productId}/options")
    public ResponseEntity<?> options(@PathVariable Long productId) {
        List<OptionView> options = inventoryService.options(productId);
        if (options.isEmpty()) {
            return ResponseEntity.status(HttpStatus.NOT_FOUND)
                .body(new ErrorResponse("PRODUCT_NOT_FOUND", "옵션 정보가 없는 상품입니다."));
        }
        return ResponseEntity.ok(new OptionsResponse(productId, options));
    }

    @ExceptionHandler(MethodArgumentNotValidException.class)
    @ResponseStatus(HttpStatus.BAD_REQUEST)
    public ErrorResponse invalidRequest() {
        return new ErrorResponse("INVALID_INVENTORY_REQUEST", "productIds는 상품 ID 목록이어야 하고 최대 20개까지 요청할 수 있습니다.");
    }

    public record CheckRequest(@NotNull @Size(max = 20) List<@NotNull Long> productIds) {}

    public record CheckResponse(List<InventoryCheck> inventories) {}

    public record OptionsResponse(Long productId, List<OptionView> options) {}

    public record ErrorResponse(String code, String message) {}
}
