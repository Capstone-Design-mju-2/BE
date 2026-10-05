package com.capstone.order.inventory;

import java.util.List;

import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

@Service
public class InventoryLoadService {

    private final InventoryRepository inventoryRepository;

    public InventoryLoadService(InventoryRepository inventoryRepository) {
        this.inventoryRepository = inventoryRepository;
    }

    @Transactional
    public LoadResult load(Long productId, List<OptionInput> options) {
        int inserted = 0;
        int updated = 0;

        for (OptionInput option : options) {
            var existing = inventoryRepository.findByProductIdAndOptionKey(productId, option.optionKey());

            if (existing.isPresent()) {
                existing.get().updateNameAndPrice(option.name(), option.price());
                updated++;
            } else {
                inventoryRepository.save(new Inventory(
                        productId, option.optionKey(), option.name(), option.price(), option.quantity()));
                inserted++;
            }
        }

        return new LoadResult(productId, inserted, updated);
    }

    public record OptionInput(String optionKey, String name, int price, int quantity) {}

    public record LoadResult(Long productId, int inserted, int updated) {}
}