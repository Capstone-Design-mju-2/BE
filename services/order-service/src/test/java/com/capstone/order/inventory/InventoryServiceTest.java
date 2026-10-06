package com.capstone.order.inventory;

import java.util.List;

import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.context.annotation.Import;

import com.capstone.order.TestcontainersConfiguration;
import com.capstone.order.inventory.InventoryLoadService.OptionInput;
import com.capstone.order.inventory.InventoryService.InventoryCheck;

import static org.assertj.core.api.Assertions.assertThat;

@SpringBootTest
@Import(TestcontainersConfiguration.class)
class InventoryServiceTest {

    @Autowired InventoryService inventoryService;
    @Autowired InventoryLoadService inventoryLoadService;
    @Autowired InventoryRepository inventoryRepository;

    @BeforeEach
    void clean() {
        inventoryRepository.deleteAll();
    }

    @Test
    void 한_상품의_옵션_재고를_합산해_응답한다() {
        inventoryLoadService.load(3001L, List.of(
                new OptionInput("100ml", "토너 100ml", 15000, 30),
                new OptionInput("200ml", "토너 200ml", 25000, 20)));

        List<InventoryCheck> results = inventoryService.check(List.of(3001L));

        assertThat(results).hasSize(1);
        assertThat(results.get(0).quantity()).isEqualTo(50);
        assertThat(results.get(0).status()).isEqualTo(InventoryService.InventoryStatus.IN_STOCK);
    }
}