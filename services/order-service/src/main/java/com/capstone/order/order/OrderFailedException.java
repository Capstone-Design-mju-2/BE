package com.capstone.order.order;

import java.util.List;

import com.capstone.order.inventory.Inventory;

public class OrderFailedException extends RuntimeException {

    public enum Reason {
        OUT_OF_STOCK, INSUFFICIENT_STOCK, OPTION_NOT_FOUND, CONCURRENT_UPDATE, LOCK_TIMEOUT, LOCK_UNAVAILABLE
    }

    private final Reason reason;
    private final Long productId;
    private final String optionKey;
    private final int requested;
    private final int available;
    private final List<SoldOutItem> soldOutItems;

    public OrderFailedException(Reason reason, Long productId, String optionKey,
                                int requested, int available) {
        super(reason.name());
        this.reason = reason;
        this.productId = productId;
        this.optionKey = optionKey;
        this.requested = requested;
        this.available = available;
        this.soldOutItems = List.of();
    }

    private OrderFailedException(OrderFailedException original, List<SoldOutItem> soldOutItems) {
        super(original.getMessage(), original);
        this.reason = original.reason;
        this.productId = original.productId;
        this.optionKey = original.optionKey;
        this.requested = original.requested;
        this.available = original.available;
        this.soldOutItems = List.copyOf(soldOutItems);
    }

    public Reason getReason() { return reason; }
    public Long getProductId() { return productId; }
    public String getOptionKey() { return optionKey; }
    public int getRequested() { return requested; }
    public int getAvailable() { return available; }
    public List<SoldOutItem> getSoldOutItems() { return soldOutItems; }

    public OrderFailedException withSoldOutItems(List<SoldOutItem> soldOutItems) {
        return new OrderFailedException(this, soldOutItems);
    }

    public static OrderFailedException shortage(Inventory inventory, int requested) {
        Reason reason = inventory.getQuantity() == 0 ? Reason.OUT_OF_STOCK : Reason.INSUFFICIENT_STOCK;
        return new OrderFailedException(reason, inventory.getProductId(), inventory.getOptionKey(),
                requested, inventory.getQuantity());
    }

    public static OrderFailedException notFound(Long productId, String optionKey, int requested) {
        return new OrderFailedException(Reason.OPTION_NOT_FOUND, productId, optionKey, requested, 0);
    }

    public static OrderFailedException conflict(Inventory inventory, int requested) {
        return new OrderFailedException(Reason.CONCURRENT_UPDATE, inventory.getProductId(),
                inventory.getOptionKey(), requested, inventory.getQuantity());
    }

    public static OrderFailedException lockTimeout(Long productId, String optionKey, int requested) {
        return new OrderFailedException(Reason.LOCK_TIMEOUT, productId, optionKey, requested, 0);
    }

    public static OrderFailedException lockUnavailable(Long productId, String optionKey, int requested) {
        return new OrderFailedException(Reason.LOCK_UNAVAILABLE, productId, optionKey, requested, 0);
    }
}
