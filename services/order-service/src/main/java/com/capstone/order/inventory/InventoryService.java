package com.capstone.order.inventory;

import org.springframework.stereotype.Service;

@Service
public class InventoryService {

    private final InventoryRepository inventoryRepository;

    public InventoryService(InventoryRepository inventoryRepository) {
        this.inventoryRepository = inventoryRepository;
    }

    public Inventory create(Long productId, int quantity) {
        return inventoryRepository.save(new Inventory(productId, quantity));
    }

    public Inventory findById(Long id) {
        return inventoryRepository.findById(id)
                .orElseThrow(() -> new IllegalArgumentException("없는 재고 id=" + id));
    }
}
