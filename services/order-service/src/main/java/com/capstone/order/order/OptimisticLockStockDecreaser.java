package com.capstone.order.order;

import com.capstone.order.inventory.Inventory;
import com.capstone.order.inventory.InventoryRepository;

public class OptimisticLockStockDecreaser implements StockDecreaser {

    private final InventoryRepository inventoryRepository;
    private final Runnable afterCheck;

    public OptimisticLockStockDecreaser(InventoryRepository inventoryRepository) {
        this(inventoryRepository, () -> {});
    }

    OptimisticLockStockDecreaser(InventoryRepository inventoryRepository, Runnable afterCheck) {
        this.inventoryRepository = inventoryRepository;
        this.afterCheck = afterCheck;
    }

    @Override
    public Inventory decrease(Long productId, String optionKey, int quantity) {
        Inventory read = inventoryRepository.findByProductIdAndOptionKey(productId, optionKey)
                .orElseThrow(() -> OrderFailedException.notFound(productId, optionKey, quantity));
        if (read.getQuantity() < quantity) {
            throw OrderFailedException.shortage(read, quantity);
        }
        afterCheck.run();
        int updated = inventoryRepository.decreaseIfVersion(read.getId(), read.getVersion(), quantity);
        Inventory current = inventoryRepository.findByProductIdAndOptionKey(productId, optionKey)
                .orElseThrow(() -> OrderFailedException.notFound(productId, optionKey, quantity));
        if (updated == 0) {
            if (current.getQuantity() < quantity) {
                throw OrderFailedException.shortage(current, quantity);
            }
            throw OrderFailedException.conflict(current, quantity);
        }
        return current;
    }
}
