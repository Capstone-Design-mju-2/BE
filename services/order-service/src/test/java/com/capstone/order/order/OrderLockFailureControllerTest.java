package com.capstone.order.order;

import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyInt;
import static org.mockito.Mockito.when;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.boot.webmvc.test.autoconfigure.AutoConfigureMockMvc;
import org.springframework.context.annotation.Import;
import org.springframework.http.MediaType;
import org.springframework.test.context.bean.override.mockito.MockitoBean;
import org.springframework.test.web.servlet.MockMvc;
import org.springframework.test.web.servlet.ResultActions;

import com.capstone.order.TestcontainersConfiguration;

@SpringBootTest
@AutoConfigureMockMvc
@Import(TestcontainersConfiguration.class)
class OrderLockFailureControllerTest {

    @Autowired
    MockMvc mockMvc;

    @MockitoBean
    StockDecreaser stockDecreaser;

    @Test
    void 락_대기_시간을_넘기면_503과_LOCK_TIMEOUT을_반환한다() throws Exception {
        when(stockDecreaser.decrease(any(), any(), anyInt()))
                .thenThrow(OrderFailedException.lockTimeout(1L, "50ml", 1));

        order()
                .andExpect(status().isServiceUnavailable())
                .andExpect(jsonPath("$.code").value("LOCK_TIMEOUT"))
                .andExpect(jsonPath("$.failedItem.optionKey").value("50ml"));
    }

    @Test
    void Redis에_연결하지_못하면_503과_LOCK_UNAVAILABLE을_반환한다() throws Exception {
        when(stockDecreaser.decrease(any(), any(), anyInt()))
                .thenThrow(OrderFailedException.lockUnavailable(1L, "50ml", 1));

        order()
                .andExpect(status().isServiceUnavailable())
                .andExpect(jsonPath("$.code").value("LOCK_UNAVAILABLE"));
    }

    private ResultActions order() throws Exception {
        return mockMvc.perform(post("/api/v1/orders")
                .contentType(MediaType.APPLICATION_JSON)
                .content("""
                        {"ordererKey": "demo", "items": [{"productId": 1, "optionKey": "50ml", "quantity": 1}]}
                        """));
    }
}