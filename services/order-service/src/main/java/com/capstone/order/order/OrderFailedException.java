package com.capstone.order.order;

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

    public OrderFailedException(Reason reason, Long productId, String optionKey,
                                int requested, int available) {
        super(reason.name());
        this.reason = reason;
        this.productId = productId;
        this.optionKey = optionKey;
        this.requested = requested;
        this.available = available;
    }

    public Reason getReason() { return reason; }
    public Long getProductId() { return productId; }
    public String getOptionKey() { return optionKey; }
    public int getRequested() { return requested; }
    public int getAvailable() { return available; }

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