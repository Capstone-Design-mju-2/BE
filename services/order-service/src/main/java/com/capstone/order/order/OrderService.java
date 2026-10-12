package com.capstone.order.order;

import java.util.Comparator;
import java.util.List;
import java.util.Map;
import java.util.TreeMap;

import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import com.capstone.order.inventory.Inventory;
import com.capstone.order.inventory.InventoryRepository;
import com.capstone.order.order.OrderFailedException.Reason;

@Service
public class OrderService {

    private final InventoryRepository inventoryRepository;
    private final OrderRepository orderRepository;

    public OrderService(InventoryRepository inventoryRepository, OrderRepository orderRepository) {
        this.inventoryRepository = inventoryRepository;
        this.orderRepository = orderRepository;
    }

    @Transactional
    public OrderResult place(String ordererKey, List<ItemInput> items) {
        Map<ItemKey, Integer> merged = new TreeMap<>(
                Comparator.comparing(ItemKey::productId).thenComparing(ItemKey::optionKey));
        for (ItemInput item : items) {
            merged.merge(new ItemKey(item.productId(), item.optionKey()), item.quantity(), Integer::sum);
        }

        Order order = new Order(ordererKey);
        for (Map.Entry<ItemKey, Integer> entry : merged.entrySet()) {
            ItemKey key = entry.getKey();
            int qty = entry.getValue();

            int updated = inventoryRepository.decreaseIfEnough(key.productId(), key.optionKey(), qty);
            Inventory inventory = inventoryRepository
                    .findByProductIdAndOptionKey(key.productId(), key.optionKey())
                    .orElseThrow(() -> new OrderFailedException(
                            Reason.OPTION_NOT_FOUND, key.productId(), key.optionKey(), qty, 0));

            if (updated == 0) {
                Reason reason = inventory.getQuantity() == 0 ? Reason.OUT_OF_STOCK : Reason.INSUFFICIENT_STOCK;
                throw new OrderFailedException(reason, key.productId(), key.optionKey(), qty, inventory.getQuantity());
            }
            order.addItem(inventory, qty);
        }

        return OrderResult.from(orderRepository.save(order));
    }

    public record ItemInput(Long productId, String optionKey, int quantity) {}

    record ItemKey(Long productId, String optionKey) {}

    public record OrderResult(Long orderId, int totalPrice, List<Line> items) {
        public record Line(Long productId, String optionKey, String name, int unitPrice, int quantity) {}

        static OrderResult from(Order order) {
            List<Line> lines = order.getItems().stream()
                    .map(i -> new Line(i.getProductId(), i.getOptionKey(), i.getName(), i.getUnitPrice(), i.getQuantity()))
                    .toList();
            return new OrderResult(order.getId(), order.getTotalPrice(), lines);
        }
    }
}