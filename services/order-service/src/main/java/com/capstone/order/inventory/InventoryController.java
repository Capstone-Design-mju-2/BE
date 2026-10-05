package com.capstone.order.inventory;

import java.util.NoSuchElementException;

import jakarta.validation.Valid;
import jakarta.validation.constraints.NotNull;
import jakarta.validation.constraints.PositiveOrZero;

import org.springframework.dao.DataIntegrityViolationException;
import org.springframework.http.HttpStatus;
import org.springframework.web.bind.MethodArgumentNotValidException;
import org.springframework.web.bind.annotation.*;

import com.capstone.order.inventory.InventoryCheckController.ErrorResponse;

@RestController
@RequestMapping("/inventory")
public class InventoryController {

    private final InventoryService inventoryService;

    public InventoryController(InventoryService inventoryService) {
        this.inventoryService = inventoryService;
    }

    
    @GetMapping("/{id}")
    public Inventory get(@PathVariable Long id) {
        return inventoryService.findById(id);
    }

    @ExceptionHandler(MethodArgumentNotValidException.class)
    @ResponseStatus(HttpStatus.BAD_REQUEST)
    public ErrorResponse invalidRequest() {
        return new ErrorResponse("INVALID_INVENTORY_REQUEST", "productId는 필수이고 quantity는 0 이상이어야 합니다.");
    }

    @ExceptionHandler(DataIntegrityViolationException.class)
    @ResponseStatus(HttpStatus.CONFLICT)
    public ErrorResponse alreadyExists() {
        return new ErrorResponse("INVENTORY_ALREADY_EXISTS", "이미 재고가 있는 상품입니다.");
    }

    @ExceptionHandler(NoSuchElementException.class)
    @ResponseStatus(HttpStatus.NOT_FOUND)
    public ErrorResponse notFound() {
        return new ErrorResponse("INVENTORY_NOT_FOUND", "재고를 찾을 수 없습니다.");
    }

    
}
