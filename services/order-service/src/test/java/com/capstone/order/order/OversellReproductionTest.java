package com.capstone.order.order;

import static org.assertj.core.api.Assertions.assertThat;

import java.util.ArrayList;
import java.util.List;
import java.util.concurrent.CyclicBarrier;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.concurrent.Future;
import java.util.concurrent.TimeUnit;

import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.boot.test.context.TestConfiguration;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Import;
import org.springframework.context.annotation.Primary;

import com.capstone.order.TestcontainersConfiguration;
import com.capstone.order.inventory.Inventory;
import com.capstone.order.inventory.InventoryRepository;
import com.capstone.order.order.OrderService.ItemInput;

@SpringBootTest
@Import({TestcontainersConfiguration.class, OversellReproductionTest.RaceConfig.class})
class OversellReproductionTest {

    static final int INITIAL_STOCK = 1;
    static final int BUYERS = 5;
    static final CyclicBarrier AFTER_CHECK = new CyclicBarrier(BUYERS);

    @TestConfiguration
    static class RaceConfig {
        @Bean
        @Primary
        StockDecreaser racingStockDecreaser(InventoryRepository inventoryRepository) {
            return new NoLockStockDecreaser(inventoryRepository, () -> {
                try {
                    AFTER_CHECK.await(5, TimeUnit.SECONDS);
                } catch (Exception e) {
                    throw new IllegalStateException("동시 주문이 출발선에 모이지 못했습니다", e);
                }
            });
        }
    }

    @Autowired OrderService orderService;
    @Autowired OrderRepository orderRepository;
    @Autowired InventoryRepository inventoryRepository;

    @BeforeEach
    void setUp() {
        orderRepository.deleteAll();
        inventoryRepository.deleteAll();
        inventoryRepository.save(new Inventory(1L, "default", "한정 상품", 10000, INITIAL_STOCK));
    }

    @Test
    void 락이_없으면_재고_1개에_동시_주문_5건이_모두_성공해_4건_초과_판매된다() throws Exception {
        ExecutorService pool = Executors.newFixedThreadPool(BUYERS);
        List<Future<Boolean>> results = new ArrayList<>();
        for (int i = 0; i < BUYERS; i++) {
            results.add(pool.submit(() -> {
                try {
                    orderService.place("demo", List.of(new ItemInput(1L, "default", 1)));
                    return true;
                } catch (OrderFailedException e) {
                    return false;
                }
            }));
        }

        int success = 0;
        for (Future<Boolean> result : results) {
            if (result.get(30, TimeUnit.SECONDS)) success++;
        }
        pool.shutdown();
        int oversold = success - INITIAL_STOCK;
        int finalStock = inventoryRepository.findByProductIdAndOptionKey(1L, "default").orElseThrow().getQuantity();
        System.out.printf("[oversell] stock=%d buyers=%d success=%d oversold=%d finalStock=%d%n",
                INITIAL_STOCK, BUYERS, success, oversold, finalStock);

        assertThat(success).isEqualTo(BUYERS);
        assertThat(oversold).isEqualTo(BUYERS - INITIAL_STOCK);
        assertThat(orderRepository.count()).isEqualTo(BUYERS);
        assertThat(finalStock).isZero();
    }
}