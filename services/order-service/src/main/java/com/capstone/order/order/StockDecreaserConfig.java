package com.capstone.order.order;

import org.springframework.beans.factory.annotation.Value;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;

import com.capstone.order.inventory.InventoryRepository;

@Configuration
public class StockDecreaserConfig {

    @Bean
    StockDecreaser stockDecreaser(@Value("${order.stock-strategy:conditional}") String strategy,
                                  InventoryRepository inventoryRepository) {
        return switch (strategy) {
            case "none" -> new NoLockStockDecreaser(inventoryRepository);
            case "conditional" -> new ConditionalUpdateStockDecreaser(inventoryRepository);
            default -> throw new IllegalArgumentException("알 수 없는 order.stock-strategy: " + strategy);
        };
    }
}