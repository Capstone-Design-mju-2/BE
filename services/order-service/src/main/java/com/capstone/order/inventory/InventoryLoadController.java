package com.capstone.order.inventory;


import java.util.List;


import jakarta.validation.Valid;
import jakarta.validation.constraints.NotNull;
import jakarta.validation.constraints.PositiveOrZero;
import jakarta.validation.constraints.Size;

import org.springframework.http.HttpStatus;
import org.springframework.web.bind.MethodArgumentNotValidException;
import org.springframework.web.bind.annotation.*;

import com.capstone.order.inventory.InventoryLoadService.LoadResult;
import com.capstone.order.inventory.InventoryLoadService.OptionInput;

@RestController
@RequestMapping("/api/v1/internal/inventories")
public class InventoryLoadController {

    private final InventoryLoadService inventoryLoadService;

    public InventoryLoadController(InventoryLoadService inventoryLoadService) {
        this.inventoryLoadService = inventoryLoadService;
    }

    @PostMapping("/load")
    public LoadResult load(@Valid @RequestBody LoadRequest request) {
        List<OptionInput> options = request.options().stream()
                .map(o -> new OptionInput(o.optionKey(), o.name(), o.price(), o.quantity()))
                .toList();
        return inventoryLoadService.load(request.productId(), options);
    }

    @ExceptionHandler(MethodArgumentNotValidException.class)
    @ResponseStatus(HttpStatus.BAD_REQUEST)
    public ErrorResponse invalidRequest() {
        return new ErrorResponse("INVALID_INVENTORY_LOAD", "요청 형식이 올바르지 않습니다.");
    }

    public record LoadRequest(
            @NotNull Long productId,
            @NotNull @Size(min = 1, max = 50) List<@Valid OptionItem> options) {}

    public record OptionItem(
            @NotNull String optionKey,
            @NotNull String name,
            @NotNull @PositiveOrZero Integer price,
            @NotNull @PositiveOrZero Integer quantity) {}

    public record ErrorResponse(String code, String message) {}
}