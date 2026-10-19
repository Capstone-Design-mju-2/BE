package com.capstone.order.order;

import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.boot.webmvc.test.autoconfigure.AutoConfigureMockMvc;
import org.springframework.context.annotation.Import;
import org.springframework.http.MediaType;
import org.springframework.test.web.servlet.MockMvc;
import org.springframework.test.web.servlet.ResultActions;

import com.capstone.order.TestcontainersConfiguration;
import com.capstone.order.inventory.Inventory;
import com.capstone.order.inventory.InventoryRepository;

import static org.assertj.core.api.Assertions.assertThat;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

@SpringBootTest
@AutoConfigureMockMvc
@Import(TestcontainersConfiguration.class)
class OrderControllerTest {

    @Autowired
    MockMvc mockMvc;

    @Autowired
    OrderRepository orderRepository;

    @Autowired
    InventoryRepository inventoryRepository;

    @BeforeEach
    void seed() {
        orderRepository.deleteAll();
        inventoryRepository.deleteAll();
        inventoryRepository.save(new Inventory(1L, "50ml", "토너 50ml", 12000, 5));
        inventoryRepository.save(new Inventory(1L, "100ml", "토너 100ml", 20000, 1));
        inventoryRepository.save(new Inventory(2L, "default", "품절 상품", 9000, 0));
    }

    @Test
    void 주문에_성공하면_201과_주문_당시_가격을_반환한다() throws Exception {
        order("""
                {"ordererKey": "demo", "items": [{"productId": 1, "optionKey": "50ml", "quantity": 2}]}
                """)
                .andExpect(status().isCreated())
                .andExpect(jsonPath("$.totalPrice").value(24000))
                .andExpect(jsonPath("$.items[0].unitPrice").value(12000))
                .andExpect(jsonPath("$.items[0].quantity").value(2));
    }

    @Test
    void 한_항목이라도_부족하면_409와_failedItem을_반환하고_다른_항목_재고는_그대로다() throws Exception {
        order("""
                {"ordererKey": "demo", "items": [
                  {"productId": 1, "optionKey": "100ml", "quantity": 1},
                  {"productId": 1, "optionKey": "50ml", "quantity": 6}
                ]}
                """)
                .andExpect(status().isConflict())
                .andExpect(jsonPath("$.code").value("INSUFFICIENT_STOCK"))
                .andExpect(jsonPath("$.failedItem.optionKey").value("50ml"))
                .andExpect(jsonPath("$.failedItem.requested").value(6))
                .andExpect(jsonPath("$.failedItem.available").value(5));

        assertThat(stock(1L, "100ml")).isEqualTo(1);
        assertThat(orderRepository.count()).isZero();
    }

    @Test
    void 재고가_0개면_409와_OUT_OF_STOCK을_반환한다() throws Exception {
        order("""
                {"ordererKey": "demo", "items": [{"productId": 2, "optionKey": "default", "quantity": 1}]}
                """)
                .andExpect(status().isConflict())
                .andExpect(jsonPath("$.code").value("OUT_OF_STOCK"))
                .andExpect(jsonPath("$.failedItem.available").value(0));
    }

    @Test
    void 없는_옵션이면_404와_OPTION_NOT_FOUND를_반환한다() throws Exception {
        order("""
                {"ordererKey": "demo", "items": [{"productId": 999, "optionKey": "default", "quantity": 1}]}
                """)
                .andExpect(status().isNotFound())
                .andExpect(jsonPath("$.code").value("OPTION_NOT_FOUND"))
                .andExpect(jsonPath("$.failedItem.productId").value(999));
    }

    @Test
    void 수량이_99를_넘으면_400을_반환한다() throws Exception {
        order("""
                {"ordererKey": "demo", "items": [{"productId": 1, "optionKey": "50ml", "quantity": 100}]}
                """)
                .andExpect(status().isBadRequest())
                .andExpect(jsonPath("$.code").value("INVALID_ORDER"))
                .andExpect(jsonPath("$.failedItem").doesNotExist());
    }

    @Test
    void optionKey가_100자를_넘으면_400을_반환한다() throws Exception {
        order("""
                {"ordererKey": "demo", "items": [{"productId": 1, "optionKey": "%s", "quantity": 1}]}
                """.formatted("a".repeat(101)))
                .andExpect(status().isBadRequest())
                .andExpect(jsonPath("$.code").value("INVALID_ORDER"));
    }

    private ResultActions order(String body) throws Exception {
        return mockMvc.perform(post("/api/v1/orders")
                .contentType(MediaType.APPLICATION_JSON)
                .content(body));
    }

    private int stock(Long productId, String optionKey) {
        return inventoryRepository.findByProductIdAndOptionKey(productId, optionKey).orElseThrow().getQuantity();
    }
}