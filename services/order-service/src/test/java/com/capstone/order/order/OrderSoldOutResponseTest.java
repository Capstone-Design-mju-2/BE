package com.capstone.order.order;

import static org.assertj.core.api.Assertions.assertThat;
import static org.hamcrest.Matchers.empty;
import static org.hamcrest.Matchers.hasSize;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

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

@SpringBootTest
@AutoConfigureMockMvc
@Import(TestcontainersConfiguration.class)
class OrderSoldOutResponseTest {

    @Autowired
    MockMvc mockMvc;

    @Autowired
    OrderRepository orderRepository;

    @Autowired
    InventoryRepository inventoryRepository;

    @BeforeEach
    void clean() {
        orderRepository.deleteAll();
        inventoryRepository.deleteAll();
    }

    @Test
    void 주문의_품절_옵션을_모두_soldOutItems에_담는다() throws Exception {
        inventoryRepository.save(new Inventory(1L, "50ml", "토너 50ml", 12000, 0));
        inventoryRepository.save(new Inventory(2L, "default", "수분크림", 25900, 0));
        inventoryRepository.save(new Inventory(3L, "default", "선크림", 18000, 5));

        order("""
                {"ordererKey": "demo", "items": [
                  {"productId": 3, "optionKey": "default", "quantity": 1},
                  {"productId": 1, "optionKey": "50ml", "quantity": 1},
                  {"productId": 2, "optionKey": "default", "quantity": 2}
                ]}
                """)
                .andExpect(status().isConflict())
                .andExpect(jsonPath("$.code").value("OUT_OF_STOCK"))
                .andExpect(jsonPath("$.failedItem.productId").value(1))
                .andExpect(jsonPath("$.soldOutItems", hasSize(2)))
                .andExpect(jsonPath("$.soldOutItems[0].productId").value(1))
                .andExpect(jsonPath("$.soldOutItems[0].optionKey").value("50ml"))
                .andExpect(jsonPath("$.soldOutItems[0].name").value("토너 50ml"))
                .andExpect(jsonPath("$.soldOutItems[0].price").value(12000))
                .andExpect(jsonPath("$.soldOutItems[0].requested").value(1))
                .andExpect(jsonPath("$.soldOutItems[1].productId").value(2))
                .andExpect(jsonPath("$.soldOutItems[1].requested").value(2));

        assertThat(stock(3L, "default")).isEqualTo(5);
    }

    @Test
    void 이_주문이_차감했다가_되돌린_옵션은_soldOutItems에_넣지_않는다() throws Exception {
        inventoryRepository.save(new Inventory(1L, "default", "토너", 12000, 1));
        inventoryRepository.save(new Inventory(2L, "default", "수분크림", 25900, 0));

        order("""
                {"ordererKey": "demo", "items": [
                  {"productId": 1, "optionKey": "default", "quantity": 1},
                  {"productId": 2, "optionKey": "default", "quantity": 1}
                ]}
                """)
                .andExpect(status().isConflict())
                .andExpect(jsonPath("$.code").value("OUT_OF_STOCK"))
                .andExpect(jsonPath("$.failedItem.productId").value(2))
                .andExpect(jsonPath("$.soldOutItems", hasSize(1)))
                .andExpect(jsonPath("$.soldOutItems[0].productId").value(2));

        assertThat(stock(1L, "default")).isEqualTo(1);
    }

    @Test
    void 재고가_남았지만_부족하면_soldOutItems는_비어_있다() throws Exception {
        inventoryRepository.save(new Inventory(1L, "default", "토너", 12000, 2));

        order("""
                {"ordererKey": "demo", "items": [{"productId": 1, "optionKey": "default", "quantity": 5}]}
                """)
                .andExpect(status().isConflict())
                .andExpect(jsonPath("$.code").value("INSUFFICIENT_STOCK"))
                .andExpect(jsonPath("$.soldOutItems", empty()));
    }

    @Test
    void 없는_옵션이면_soldOutItems는_비어_있다() throws Exception {
        order("""
                {"ordererKey": "demo", "items": [{"productId": 999, "optionKey": "default", "quantity": 1}]}
                """)
                .andExpect(status().isNotFound())
                .andExpect(jsonPath("$.code").value("OPTION_NOT_FOUND"))
                .andExpect(jsonPath("$.soldOutItems", empty()));
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
