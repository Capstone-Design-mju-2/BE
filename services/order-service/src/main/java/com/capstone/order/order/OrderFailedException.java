package com.capstone.order.order;

public class OrderFailedException extends RuntimeException {

    public enum Reason { OUT_OF_STOCK, INSUFFICIENT_STOCK, OPTION_NOT_FOUND }

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
}
