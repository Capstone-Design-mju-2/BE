package com.capstone.order.order;

import static org.assertj.core.api.Assertions.assertThat;

import java.util.ArrayList;
import java.util.List;
import java.util.Map;
import java.util.TreeMap;
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
@Import({TestcontainersConfiguration.class, OversellReproductionTest.SwitchConfig.class})
class OversellReproductionTest {

    static final int INITIAL_STOCK = 1;
    static final int BUYERS = 5;

    static class SwitchableStockDecreaser implements StockDecreaser {
        volatile StockDecreaser delegate;

        @Override
        public Inventory decrease(Long productId, String optionKey, int quantity) {
            return delegate.decrease(productId, optionKey, quantity);
        }
    }

    @TestConfiguration
    static class SwitchConfig {
        @Bean
        @Primary
        SwitchableStockDecreaser switchableStockDecreaser() {
            return new SwitchableStockDecreaser();
        }
    }

    @Autowired SwitchableStockDecreaser decreaser;
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
        decreaser.delegate = new NoLockStockDecreaser(inventoryRepository, lineUp(new CyclicBarrier(BUYERS)));

        Map<String, Long> outcomes = race("none");

        assertThat(outcomes).containsExactlyInAnyOrderEntriesOf(Map.of("SUCCESS", 5L));
        assertThat(orderRepository.count()).isEqualTo(5);
        assertThat(finalStock()).isZero();
    }

    @Test
    void 비관적_락이면_1건만_성공하고_초과_판매가_없다() throws Exception {
        decreaser.delegate = new PessimisticLockStockDecreaser(inventoryRepository, lineUp(new CyclicBarrier(BUYERS)));

        Map<String, Long> outcomes = race("pessimistic");

        assertThat(outcomes).containsExactlyInAnyOrderEntriesOf(Map.of("SUCCESS", 1L, "OUT_OF_STOCK", 4L));
        assertThat(orderRepository.count()).isEqualTo(INITIAL_STOCK);
        assertThat(finalStock()).isZero();
    }

    @Test
    void 낙관적_락이면_1건만_성공하고_초과_판매가_없다() throws Exception {
        decreaser.delegate = new OptimisticLockStockDecreaser(inventoryRepository, lineUp(new CyclicBarrier(BUYERS)));

        Map<String, Long> outcomes = race("optimistic");

        assertThat(outcomes).containsExactlyInAnyOrderEntriesOf(Map.of("SUCCESS", 1L, "OUT_OF_STOCK", 4L));
        assertThat(orderRepository.count()).isEqualTo(INITIAL_STOCK);
        assertThat(finalStock()).isZero();
    }

    private Map<String, Long> race(String strategy) throws Exception {
        ExecutorService pool = Executors.newFixedThreadPool(BUYERS);
        List<Future<String>> futures = new ArrayList<>();
        for (int i = 0; i < BUYERS; i++) {
            futures.add(pool.submit(() -> {
                try {
                    orderService.place("demo", List.of(new ItemInput(1L, "default", 1)));
                    return "SUCCESS";
                } catch (OrderFailedException e) {
                    return e.getReason().name();
                }
            }));
        }
        Map<String, Long> outcomes = new TreeMap<>();
        for (Future<String> future : futures) {
            outcomes.merge(future.get(30, TimeUnit.SECONDS), 1L, Long::sum);
        }
        pool.shutdown();
        long success = outcomes.getOrDefault("SUCCESS", 0L);
        System.out.printf("[oversell] strategy=%s stock=%d buyers=%d outcomes=%s oversold=%d finalStock=%d%n",
                strategy, INITIAL_STOCK, BUYERS, outcomes, Math.max(0, success - INITIAL_STOCK), finalStock());
        return outcomes;
    }

    private int finalStock() {
        return inventoryRepository.findByProductIdAndOptionKey(1L, "default").orElseThrow().getQuantity();
    }

    private static Runnable lineUp(CyclicBarrier barrier) {
        return () -> {
            try {
                barrier.await(5, TimeUnit.SECONDS);
            } catch (Exception e) {
                throw new IllegalStateException("동시 주문이 출발선에 모이지 못했습니다", e);
            }
        };
    }
}