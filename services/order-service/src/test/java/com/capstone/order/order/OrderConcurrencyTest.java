package com.capstone.order.order;

import static org.assertj.core.api.Assertions.assertThat;

import java.util.ArrayList;
import java.util.List;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.concurrent.Future;

import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.context.annotation.Import;

import com.capstone.order.TestcontainersConfiguration;
import com.capstone.order.inventory.Inventory;
import com.capstone.order.inventory.InventoryRepository;
import com.capstone.order.order.OrderService.ItemInput;

@SpringBootTest
@Import(TestcontainersConfiguration.class)
class OrderConcurrencyTest {

    @Autowired OrderService orderService;
    @Autowired OrderRepository orderRepository;
    @Autowired InventoryRepository inventoryRepository;

    @BeforeEach
    void setUp() {
        orderRepository.deleteAll();
        inventoryRepository.deleteAll();
        inventoryRepository.save(new Inventory(1L, "50ml", "토너 50ml", 12000, 5));
    }

    @Test
    void 동시에_10명이_1개씩_주문해도_재고_5개만큼만_팔린다() throws Exception {
        int buyers = 10;
        ExecutorService pool = Executors.newFixedThreadPool(buyers);
        CountDownLatch start = new CountDownLatch(1);
        List<Future<Boolean>> results = new ArrayList<>();

        for (int i = 0; i < buyers; i++) {
            results.add(pool.submit(() -> {
                start.await();
                try {
                    orderService.place("demo", List.of(new ItemInput(1L, "50ml", 1)));
                    return true;
                } catch (OrderFailedException e) {
                    return false;
                }
            }));
        }
        start.countDown();

        int success = 0;
        for (Future<Boolean> result : results) {
            if (result.get()) success++;
        }
        pool.shutdown();

        assertThat(success).isEqualTo(5);
        assertThat(orderRepository.count()).isEqualTo(5);
        assertThat(inventoryRepository.findByProductIdAndOptionKey(1L, "50ml").orElseThrow().getQuantity()).isZero();
    }
}