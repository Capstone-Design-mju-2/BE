package com.capstone.order.inventory;

import org.springframework.web.bind.annotation.*;

@RestController
@RequestMapping("/inventory")
public class InventoryController {

    private final InventoryService inventoryService;

    public InventoryController(InventoryService inventoryService) {
        this.inventoryService = inventoryService;
    }

    @PostMapping
    public Inventory create(@RequestBody CreateInventoryRequest request) {
        return inventoryService.create(request.productId(), request.quantity());
    }

    @GetMapping("/{id}")
    public Inventory get(@PathVariable Long id) {
        return inventoryService.findById(id);
    }

    record CreateInventoryRequest(Long productId, int quantity) {}
}