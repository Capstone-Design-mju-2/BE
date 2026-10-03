package com.capstone.order.inventory;

import java.util.List;

import jakarta.validation.Valid;
import jakarta.validation.constraints.NotNull;
import jakarta.validation.constraints.Size;

import org.springframework.http.HttpStatus;
import org.springframework.web.bind.MethodArgumentNotValidException;
import org.springframework.web.bind.annotation.*;

import com.capstone.order.inventory.InventoryService.InventoryCheck;

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

    @ExceptionHandler(MethodArgumentNotValidException.class)
    @ResponseStatus(HttpStatus.BAD_REQUEST)
    public ErrorResponse invalidRequest() {
        return new ErrorResponse("INVALID_INVENTORY_REQUEST", "productIds는 상품 ID 목록이어야 하고 최대 20개까지 요청할 수 있습니다.");
    }

    public record CheckRequest(@NotNull @Size(max = 20) List<@NotNull Long> productIds) {}

    public record CheckResponse(List<InventoryCheck> inventories) {}

    public record ErrorResponse(String code, String message) {}
}
