package com.capstone.order.order;

import com.capstone.order.inventory.Inventory;
import com.capstone.order.inventory.InventoryRepository;

public class NoLockStockDecreaser implements StockDecreaser {

    private final InventoryRepository inventoryRepository;
    private final Runnable afterCheck;

    public NoLockStockDecreaser(InventoryRepository inventoryRepository) {
        this(inventoryRepository, () -> {});
    }

    NoLockStockDecreaser(InventoryRepository inventoryRepository, Runnable afterCheck) {
        this.inventoryRepository = inventoryRepository;
        this.afterCheck = afterCheck;
    }

    @Override
    public Inventory decrease(Long productId, String optionKey, int quantity) {
        Inventory inventory = inventoryRepository.findByProductIdAndOptionKey(productId, optionKey)
                .orElseThrow(() -> OrderFailedException.notFound(productId, optionKey, quantity));
        if (inventory.getQuantity() < quantity) {
            throw OrderFailedException.shortage(inventory, quantity);
        }
        afterCheck.run();
        inventory.decrease(quantity);
        return inventory;
    }
}