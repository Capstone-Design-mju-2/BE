package com.capstone.order.order;

import com.capstone.order.inventory.Inventory;

public interface StockDecreaser {

    Inventory decrease(Long productId, String optionKey, int quantity);
}
