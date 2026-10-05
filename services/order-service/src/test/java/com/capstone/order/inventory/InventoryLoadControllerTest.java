package com.capstone.order.inventory;

import java.util.List;

import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;

import com.capstone.order.inventory.InventoryLoadService.OptionInput;

import static org.assertj.core.api.Assertions.assertThat;

@SpringBootTest
class InventoryLoadControllerTest {

    @Autowired InventoryLoadService inventoryLoadService;
    @Autowired InventoryRepository inventoryRepository;

    @Test
    void 같은_적재_요청을_두_번_보내도_재고가_변하지_않는다() {
        Long productId = 5001L;
        List<OptionInput> options = List.of(new OptionInput("100ml", "토너 100ml", 15000, 30));

        inventoryLoadService.load(productId, options);
        var afterFirst = inventoryRepository.findByProductIdAndOptionKey(productId, "100ml").orElseThrow();
        assertThat(afterFirst.getQuantity()).isEqualTo(30);

        inventoryLoadService.load(productId, options);
        var afterSecond = inventoryRepository.findByProductIdAndOptionKey(productId, "100ml").orElseThrow();

        assertThat(afterSecond.getQuantity()).isEqualTo(30);
    }
}