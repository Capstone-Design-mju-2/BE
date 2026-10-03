package com.capstone.order.inventory;

import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.boot.webmvc.test.autoconfigure.AutoConfigureMockMvc;
import org.springframework.context.annotation.Import;
import org.springframework.http.MediaType;
import org.springframework.test.web.servlet.MockMvc;
import org.springframework.test.web.servlet.RequestBuilder;

import com.capstone.order.TestcontainersConfiguration;

import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

@SpringBootTest
@AutoConfigureMockMvc
@Import(TestcontainersConfiguration.class)
class InventoryControllerTest {

    @Autowired
    MockMvc mockMvc;

    @Autowired
    InventoryRepository inventoryRepository;

    @BeforeEach
    void clean() {
        inventoryRepository.deleteAll();
    }

    @Test
    void 같은_상품을_다시_만들면_409를_반환한다() throws Exception {
        mockMvc.perform(create("{\"productId\": 7, \"quantity\": 3}")).andExpect(status().isOk());

        mockMvc.perform(create("{\"productId\": 7, \"quantity\": 3}"))
                .andExpect(status().isConflict())
                .andExpect(jsonPath("$.code").value("INVENTORY_ALREADY_EXISTS"));
    }

    @Test
    void 음수_수량이나_빠진_값은_400을_반환한다() throws Exception {
        mockMvc.perform(create("{\"productId\": 7, \"quantity\": -1}"))
                .andExpect(status().isBadRequest())
                .andExpect(jsonPath("$.code").value("INVALID_INVENTORY_REQUEST"));
        mockMvc.perform(create("{\"quantity\": 3}")).andExpect(status().isBadRequest());
        mockMvc.perform(create("{\"productId\": 7}")).andExpect(status().isBadRequest());
    }

    @Test
    void 없는_재고를_조회하면_404를_반환한다() throws Exception {
        mockMvc.perform(get("/inventory/999999"))
                .andExpect(status().isNotFound())
                .andExpect(jsonPath("$.code").value("INVENTORY_NOT_FOUND"));
    }

    private static RequestBuilder create(String body) {
        return post("/inventory").contentType(MediaType.APPLICATION_JSON).content(body);
    }
}
