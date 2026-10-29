package com.capstone.order.order;

import org.springframework.beans.factory.annotation.Value;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;

import com.capstone.order.inventory.InventoryRepository;

@Configuration
public class StockDecreaserConfig {

    @Bean
    StockDecreaser stockDecreaser(@Value("${order.stock-strategy:conditional}") String strategy,
                                  @Value("${order.redisson.address}") String redissonAddress,
                                  @Value("${order.redisson.timeout-millis}") int redissonTimeoutMillis,
                                  @Value("${order.redisson.wait-millis}") long redissonWaitMillis,
                                  InventoryRepository inventoryRepository) {
        return switch (strategy) {
            case "none" -> new NoLockStockDecreaser(inventoryRepository);
            case "conditional" -> new ConditionalUpdateStockDecreaser(inventoryRepository);
            case "pessimistic" -> new PessimisticLockStockDecreaser(inventoryRepository);
            case "optimistic" -> new OptimisticLockStockDecreaser(inventoryRepository);
            case "redisson" -> new RedissonLockStockDecreaser(inventoryRepository,
                    RedissonLockStockDecreaser.connect(redissonAddress, redissonTimeoutMillis), redissonWaitMillis);
            default -> throw new IllegalArgumentException("알 수 없는 order.stock-strategy: " + strategy);
        };
    }
}