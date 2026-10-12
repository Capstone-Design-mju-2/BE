package com.capstone.order.order;

import com.capstone.order.inventory.Inventory;
import com.capstone.order.inventory.InventoryRepository;

public class NoLockStockDecreaser implements StockDecreaser {

    private final InventoryRepository inventoryRepository;

    public NoLockStockDecreaser(InventoryRepository inventoryRepository) {
        this.inventoryRepository = inventoryRepository;
    }

    @Override
    public Inventory decrease(Long productId, String optionKey, int quantity) {
        Inventory inventory = inventoryRepository.findByProductIdAndOptionKey(productId, optionKey)
                .orElseThrow(() -> OrderFailedException.notFound(productId, optionKey, quantity));
        if (inventory.getQuantity() < quantity) {
            throw OrderFailedException.shortage(inventory, quantity);
        }
        inventory.decrease(quantity);
        return inventory;
    }
}