package com.capstone.order.order;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;

import java.util.List;

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
class OrderServiceTest {

    @Autowired OrderService orderService;
    @Autowired OrderRepository orderRepository;
    @Autowired InventoryRepository inventoryRepository;

    @BeforeEach
    void setUp() {
        orderRepository.deleteAll();
        inventoryRepository.deleteAll();
        inventoryRepository.save(new Inventory(1L, "50ml", "토너 50ml", 12000, 5));
        inventoryRepository.save(new Inventory(1L, "100ml", "토너 100ml", 20000, 1));
    }

    @Test
    void 재고가_충분하면_차감하고_주문_당시_가격으로_주문을_만든다() {
        var result = orderService.place("demo", List.of(new ItemInput(1L, "50ml", 2)));

        assertThat(result.totalPrice()).isEqualTo(24000);
        assertThat(result.items().get(0).unitPrice()).isEqualTo(12000);
        assertThat(stock("50ml")).isEqualTo(3);
    }

    @Test
    void 한_항목이라도_부족하면_전부_롤백한다() {
        assertThatThrownBy(() -> orderService.place("demo", List.of(
                new ItemInput(1L, "50ml", 2),
                new ItemInput(1L, "100ml", 3))))
                .isInstanceOf(OrderFailedException.class)
                .extracting("reason").isEqualTo(OrderFailedException.Reason.INSUFFICIENT_STOCK);

        assertThat(stock("50ml")).isEqualTo(5);
        assertThat(orderRepository.count()).isZero();
    }

    private int stock(String optionKey) {
        return inventoryRepository.findByProductIdAndOptionKey(1L, optionKey).orElseThrow().getQuantity();
    }
}