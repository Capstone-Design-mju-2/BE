package com.capstone.order.order;

import com.capstone.order.inventory.Inventory;
import com.capstone.order.inventory.InventoryRepository;

public class ConditionalUpdateStockDecreaser implements StockDecreaser {

    private final InventoryRepository inventoryRepository;

    public ConditionalUpdateStockDecreaser(InventoryRepository inventoryRepository) {
        this.inventoryRepository = inventoryRepository;
    }

    @Override
    public Inventory decrease(Long productId, String optionKey, int quantity) {
        int updated = inventoryRepository.decreaseIfEnough(productId, optionKey, quantity);
        Inventory inventory = inventoryRepository.findByProductIdAndOptionKey(productId, optionKey)
                .orElseThrow(() -> OrderFailedException.notFound(productId, optionKey, quantity));
        if (updated == 0) {
            throw OrderFailedException.shortage(inventory, quantity);
        }
        return inventory;
    }
}