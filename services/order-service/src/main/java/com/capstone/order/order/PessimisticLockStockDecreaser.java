package com.capstone.order.order;

import com.capstone.order.inventory.Inventory;
import com.capstone.order.inventory.InventoryRepository;

public class PessimisticLockStockDecreaser implements StockDecreaser {

    private final InventoryRepository inventoryRepository;
    private final Runnable beforeLock;

    public PessimisticLockStockDecreaser(InventoryRepository inventoryRepository) {
        this(inventoryRepository, () -> {});
    }

    PessimisticLockStockDecreaser(InventoryRepository inventoryRepository, Runnable beforeLock) {
        this.inventoryRepository = inventoryRepository;
        this.beforeLock = beforeLock;
    }

    @Override
    public Inventory decrease(Long productId, String optionKey, int quantity) {
        beforeLock.run();
        Inventory inventory = inventoryRepository.findForUpdate(productId, optionKey)
                .orElseThrow(() -> OrderFailedException.notFound(productId, optionKey, quantity));
        if (inventory.getQuantity() < quantity) {
            throw OrderFailedException.shortage(inventory, quantity);
        }
        inventory.decrease(quantity);
        return inventory;
    }
}
