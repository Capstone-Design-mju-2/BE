package com.capstone.order.order;

import com.capstone.order.inventory.Inventory;

public record SoldOutItem(Long productId, String optionKey, String name, int price, int requested) {

    static SoldOutItem of(Inventory inventory, int requested) {
        return new SoldOutItem(inventory.getProductId(), inventory.getOptionKey(), inventory.getName(),
                inventory.getPrice(), requested);
    }
}
