package com.capstone.order.inventory;

import java.time.LocalDate;
import java.time.ZoneId;
import java.util.stream.Collectors;
import java.util.stream.LongStream;

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

import static org.hamcrest.Matchers.contains;
import static org.hamcrest.Matchers.nullValue;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

@SpringBootTest
@AutoConfigureMockMvc
@Import(TestcontainersConfiguration.class)
class InventoryCheckControllerTest {

    @Autowired
    MockMvc mockMvc;

    @Autowired
    InventoryRepository inventoryRepository;

    @BeforeEach
    void seed() {
        inventoryRepository.deleteAll();
        inventoryRepository.save(new Inventory(101L, "default", "상품 101", 10000, 12));
        inventoryRepository.save(new Inventory(102L, "default", "상품 102", 10000, 0));
        inventoryRepository.save(new Inventory(103L, "12", "크림 50ml 2개", 23900, 0));
        inventoryRepository.save(new Inventory(103L, "11", "크림 50ml", 12900, 3));
    }

    @Test
    void 옵션을_optionKey_순서로_가격_수량_상태와_함께_반환한다() throws Exception {
        mockMvc.perform(get("/api/v1/inventories/103/options"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.productId").value(103))
                .andExpect(jsonPath("$.options[*].optionKey").value(contains("11", "12")))
                .andExpect(jsonPath("$.options[0].name").value("크림 50ml"))
                .andExpect(jsonPath("$.options[0].price").value(12900))
                .andExpect(jsonPath("$.options[0].quantity").value(3))
                .andExpect(jsonPath("$.options[0].status").value("IN_STOCK"))
                .andExpect(jsonPath("$.options[1].quantity").value(0))
                .andExpect(jsonPath("$.options[1].status").value("OUT_OF_STOCK"));
    }

    @Test
    void 옵션이_없는_상품이면_404와_PRODUCT_NOT_FOUND를_반환한다() throws Exception {
        mockMvc.perform(get("/api/v1/inventories/999/options"))
                .andExpect(status().isNotFound())
                .andExpect(jsonPath("$.code").value("PRODUCT_NOT_FOUND"))
                .andExpect(jsonPath("$.message").value("옵션 정보가 없는 상품입니다."));
    }

    @Test
    void 재고_있음_품절_없음을_한_번에_요청하면_세_개를_각각의_상태로_반환한다() throws Exception {
        String tomorrow = LocalDate.now(ZoneId.of("Asia/Seoul")).plusDays(1).toString();

        mockMvc.perform(check("[101, 102, 999]"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.inventories.length()").value(3))
                .andExpect(jsonPath("$.inventories[?(@.productId == 101)].status").value("IN_STOCK"))
                .andExpect(jsonPath("$.inventories[?(@.productId == 101)].quantity").value(12))
                .andExpect(jsonPath("$.inventories[?(@.productId == 101)].estimatedDeliveryDate").value(tomorrow))
                .andExpect(jsonPath("$.inventories[?(@.productId == 102)].status").value("OUT_OF_STOCK"))
                .andExpect(jsonPath("$.inventories[?(@.productId == 102)].quantity").value(0))
                .andExpect(jsonPath("$.inventories[?(@.productId == 102)].estimatedDeliveryDate").value(contains(nullValue())))
                .andExpect(jsonPath("$.inventories[?(@.productId == 999)].status").value("NOT_FOUND"))
                .andExpect(jsonPath("$.inventories[?(@.productId == 999)].quantity").value(contains(nullValue())))
                .andExpect(jsonPath("$.inventories[?(@.productId == 999)].estimatedDeliveryDate").value(contains(nullValue())));
    }

    @Test
    void 스무_개는_허용하고_스물한_개는_400과_오류_본문을_반환한다() throws Exception {
        mockMvc.perform(check(ids(20)))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.inventories.length()").value(20));

        mockMvc.perform(check(ids(21)))
                .andExpect(status().isBadRequest())
                .andExpect(jsonPath("$.code").value("INVALID_INVENTORY_REQUEST"))
                .andExpect(jsonPath("$.message").isNotEmpty());
    }

    private static RequestBuilder check(String productIds) {
        return post("/api/v1/inventories/check")
                .contentType(MediaType.APPLICATION_JSON)
                .content("{\"productIds\": " + productIds + "}");
    }

    private static String ids(int count) {
        return LongStream.rangeClosed(1, count)
                .mapToObj(Long::toString)
                .collect(Collectors.joining(", ", "[", "]"));
    }
}
