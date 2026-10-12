package com.capstone.order.order;

import java.util.Comparator;
import java.util.List;
import java.util.Map;
import java.util.TreeMap;

import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import com.capstone.order.inventory.Inventory;

@Service
public class OrderService {

    private final StockDecreaser stockDecreaser;
    private final OrderRepository orderRepository;

    public OrderService(StockDecreaser stockDecreaser, OrderRepository orderRepository) {
        this.stockDecreaser = stockDecreaser;
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
            Inventory inventory = stockDecreaser.decrease(key.productId(), key.optionKey(), entry.getValue());
            order.addItem(inventory, entry.getValue());
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