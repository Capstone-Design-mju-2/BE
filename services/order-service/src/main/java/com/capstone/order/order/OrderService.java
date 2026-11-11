package com.capstone.order.order;

import java.util.Comparator;
import java.util.List;
import java.util.Map;
import java.util.Optional;
import java.util.TreeMap;

import org.springframework.dao.DataIntegrityViolationException;
import org.springframework.stereotype.Service;
import org.springframework.transaction.PlatformTransactionManager;
import org.springframework.transaction.support.TransactionTemplate;

import com.capstone.order.inventory.Inventory;

@Service
public class OrderService {

    private final StockDecreaser stockDecreaser;
    private final OrderRepository orderRepository;
    private final TransactionTemplate transaction;

    public OrderService(StockDecreaser stockDecreaser, OrderRepository orderRepository,
                        PlatformTransactionManager transactionManager) {
        this.stockDecreaser = stockDecreaser;
        this.orderRepository = orderRepository;
        this.transaction = new TransactionTemplate(transactionManager);
    }

    public OrderResult place(String ordererKey, List<ItemInput> items) {
        return place(ordererKey, null, items);
    }

    /** A requestId that already made an order gets that order back without taking stock again (ADR-119). */
    public OrderResult place(String ordererKey, String requestId, List<ItemInput> items) {
        if (requestId == null) {
            return transaction.execute(status -> create(ordererKey, null, items));
        }
        Optional<OrderResult> earlier = findByRequestId(requestId);
        if (earlier.isPresent()) {
            return earlier.get();
        }
        try {
            return transaction.execute(status -> create(ordererKey, requestId, items));
        } catch (OrderFailedException | DataIntegrityViolationException e) {
            // A copy of this request sent at the same time may have committed first. This attempt rolled back,
            // so the stock it took is back and the first order is the answer.
            return findByRequestId(requestId).orElseThrow(() -> e);
        }
    }

    private Optional<OrderResult> findByRequestId(String requestId) {
        return transaction.execute(status -> orderRepository.findByRequestId(requestId).map(OrderResult::from));
    }

    private OrderResult create(String ordererKey, String requestId, List<ItemInput> items) {
        Map<ItemKey, Integer> merged = new TreeMap<>(
                Comparator.comparing(ItemKey::productId).thenComparing(ItemKey::optionKey));
        for (ItemInput item : items) {
            merged.merge(new ItemKey(item.productId(), item.optionKey()), item.quantity(), Integer::sum);
        }

        Order order = new Order(ordererKey, requestId);
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