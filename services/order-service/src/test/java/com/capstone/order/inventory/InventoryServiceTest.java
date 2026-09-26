package com.capstone.order.inventory;

import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;

import static org.assertj.core.api.Assertions.assertThat;

@SpringBootTest
class InventoryServiceTest {

    @Autowired
    InventoryService inventoryService;

    @Test
    void 재고를_생성하고_조회한다() {
        Inventory saved = inventoryService.create(1L, 100);

        Inventory found = inventoryService.findById(saved.getId());

        assertThat(found.getProductId()).isEqualTo(1L);
        assertThat(found.getQuantity()).isEqualTo(100);
    }
}