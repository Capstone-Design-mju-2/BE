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

    

    public Inventory findById(Long id) {
        return inventoryRepository.findById(id).orElseThrow();
    }

    @Transactional(readOnly = true)
    public List<InventoryCheck> check(List<Long> productIds) {
        var requested = new LinkedHashSet<>(productIds);
        Map<Long, List<Inventory>> byProduct = inventoryRepository.findAllByProductIdIn(requested).stream()
            .collect(Collectors.groupingBy(Inventory::getProductId));

        return requested.stream()
            .map(productId -> toCheck(productId, byProduct.get(productId)))
            .toList();
    }

    private InventoryCheck toCheck(Long productId, List<Inventory> options) {
       if (options == null || options.isEmpty()) {
        return new InventoryCheck(productId, InventoryStatus.NOT_FOUND, null, null);
        }
        int total = options.stream().mapToInt(Inventory::getQuantity).sum();
        if (total == 0) {
            return new InventoryCheck(productId, InventoryStatus.OUT_OF_STOCK, 0, null);
        }
        return new InventoryCheck(productId, InventoryStatus.IN_STOCK, total,
            LocalDate.now(SEOUL).plusDays(1));
    }

    public enum InventoryStatus { IN_STOCK, OUT_OF_STOCK, NOT_FOUND }

    public record InventoryCheck(Long productId, InventoryStatus status, Integer quantity,
                                 LocalDate estimatedDeliveryDate) {}
}
