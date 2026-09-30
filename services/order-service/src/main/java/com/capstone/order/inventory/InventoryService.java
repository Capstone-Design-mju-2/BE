package com.capstone.order.inventory;

import java.time.LocalDate;
import java.time.ZoneId;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Map;
import java.util.function.Function;
import java.util.stream.Collectors;

import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

@Service
public class InventoryService {

    private static final ZoneId SEOUL = ZoneId.of("Asia/Seoul");

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

    @Transactional(readOnly = true)
    public List<InventoryCheck> check(List<Long> productIds) {
        var requested = new LinkedHashSet<>(productIds);
        Map<Long, Inventory> found = inventoryRepository.findAllByProductIdIn(requested).stream()
                .collect(Collectors.toMap(Inventory::getProductId, Function.identity()));

        return requested.stream()
                .map(productId -> toCheck(productId, found.get(productId)))
                .toList();
    }

    private InventoryCheck toCheck(Long productId, Inventory inventory) {
        if (inventory == null) {
            return new InventoryCheck(productId, InventoryStatus.NOT_FOUND, null, null);
        }
        if (inventory.getQuantity() == 0) {
            return new InventoryCheck(productId, InventoryStatus.OUT_OF_STOCK, 0, null);
        }
        return new InventoryCheck(productId, InventoryStatus.IN_STOCK, inventory.getQuantity(),
                LocalDate.now(SEOUL).plusDays(1));
    }

    public enum InventoryStatus { IN_STOCK, OUT_OF_STOCK, NOT_FOUND }

    public record InventoryCheck(Long productId, InventoryStatus status, Integer quantity,
                                 LocalDate estimatedDeliveryDate) {}
}
