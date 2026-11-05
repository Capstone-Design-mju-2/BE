package com.capstone.order;

import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.options;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.header;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.boot.webmvc.test.autoconfigure.AutoConfigureMockMvc;
import org.springframework.context.annotation.Import;
import org.springframework.test.web.servlet.MockMvc;
import org.springframework.test.web.servlet.ResultActions;

@SpringBootTest
@AutoConfigureMockMvc
@Import(TestcontainersConfiguration.class)
class WebCorsConfigTest {

    @Autowired
    MockMvc mockMvc;

    @Test
    void 허용한_프론트_주소에서_보낸_주문_요청은_통과한다() throws Exception {
        preflight("/api/v1/orders", "http://localhost:5173")
                .andExpect(status().isOk())
                .andExpect(header().string("Access-Control-Allow-Origin", "http://localhost:5173"));
    }

    @Test
    void 허용하지_않은_주소에서_보낸_요청은_막는다() throws Exception {
        preflight("/api/v1/orders", "http://evil.example")
                .andExpect(status().isForbidden());
    }

    @Test
    void 수집기_전용_적재_API는_브라우저에_열지_않는다() throws Exception {
        preflight("/api/v1/internal/inventories/load", "http://localhost:5173")
                .andExpect(header().doesNotExist("Access-Control-Allow-Origin"));
    }

    private ResultActions preflight(String path, String origin) throws Exception {
        return mockMvc.perform(options(path)
                .header("Origin", origin)
                .header("Access-Control-Request-Method", "POST")
                .header("Access-Control-Request-Headers", "Content-Type"));
    }
}
