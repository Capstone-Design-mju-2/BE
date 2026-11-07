package com.capstone.gateway;

import static org.assertj.core.api.Assertions.assertThat;

import java.io.IOException;
import java.io.OutputStream;
import java.net.InetSocketAddress;
import java.net.ServerSocket;
import java.nio.charset.StandardCharsets;
import java.util.concurrent.Executors;
import java.util.concurrent.atomic.AtomicReference;

import org.junit.jupiter.api.AfterAll;
import org.junit.jupiter.api.BeforeAll;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.boot.webtestclient.autoconfigure.AutoConfigureWebTestClient;
import org.springframework.http.MediaType;
import org.springframework.test.context.DynamicPropertyRegistry;
import org.springframework.test.context.DynamicPropertySource;
import org.springframework.test.web.reactive.server.WebTestClient;

import com.sun.net.httpserver.HttpServer;

import io.github.resilience4j.circuitbreaker.CircuitBreaker;
import io.github.resilience4j.circuitbreaker.CircuitBreakerRegistry;

@SpringBootTest(webEnvironment = SpringBootTest.WebEnvironment.RANDOM_PORT,
        properties = "resilience4j.timelimiter.instances.catalog.timeout-duration=1s")
@AutoConfigureWebTestClient
class GatewayRoutingTest {

    /** Stands in for catalog: notes the request id it got; /slow answers after 3 s, /busy with its own 503. */
    static HttpServer catalog;
    static final AtomicReference<String> seenRequestId = new AtomicReference<>();
    static final AtomicReference<String> seenPath = new AtomicReference<>();

    @Autowired
    WebTestClient client;

    @Autowired
    CircuitBreakerRegistry circuitBreakers;

    @BeforeAll
    static void startCatalog() throws IOException {
        catalog = HttpServer.create(new InetSocketAddress("127.0.0.1", 0), 0);
        catalog.setExecutor(Executors.newCachedThreadPool());
        catalog.createContext("/", exchange -> {
            seenRequestId.set(exchange.getRequestHeaders().getFirst("X-Request-Id"));
            String path = exchange.getRequestURI().getPath();
            seenPath.set(path);
            if (path.endsWith("/slow")) {
                try {
                    Thread.sleep(3000);
                } catch (InterruptedException e) {
                    Thread.currentThread().interrupt();
                }
            }
            int status = path.endsWith("/busy") ? 503 : 200;
            byte[] body = (status == 503 ? "{\"code\":\"LOCK_TIMEOUT\"}" : "{\"products\":[]}")
                    .getBytes(StandardCharsets.UTF_8);
            exchange.getResponseHeaders().set("Content-Type", "application/json");
            exchange.sendResponseHeaders(status, body.length);
            try (OutputStream out = exchange.getResponseBody()) {
                out.write(body);
            }
        });
        catalog.start();
    }

    @AfterAll
    static void stopCatalog() {
        catalog.stop(0);
    }

    @DynamicPropertySource
    static void services(DynamicPropertyRegistry registry) throws IOException {
        registry.add("CATALOG_SERVICE_URL", () -> "http://127.0.0.1:" + catalog.getAddress().getPort());
        registry.add("AGENT_SERVICE_URL", () -> "http://127.0.0.1:" + catalog.getAddress().getPort());
        // Nothing listens there, so every call on the order route fails to connect.
        try (ServerSocket socket = new ServerSocket(0)) {
            int unused = socket.getLocalPort();
            registry.add("ORDER_SERVICE_URL", () -> "http://127.0.0.1:" + unused);
        }
    }

    @Test
    void 경로에_맞는_서비스로_넘기고_요청_ID를_서비스와_응답에_같이_준다() {
        String id = client.get().uri("/api/v1/products?category=104001").exchange()
                .expectStatus().isOk()
                .returnResult(String.class).getResponseHeaders().getFirst("X-Request-Id");

        assertThat(id).isNotBlank().isEqualTo(seenRequestId.get());
    }

    @Test
    void 피부_분석_요청도_agent로_넘긴다() {
        client.post().uri("/api/v1/profile/insights").contentType(MediaType.APPLICATION_JSON)
                .bodyValue("{}").exchange().expectStatus().isOk();
        assertThat(seenPath.get()).isEqualTo("/api/v1/profile/insights");
    }

    @Test
    void 받은_요청_ID가_토큰이면_그대로_쓰고_아니면_새로_만든다() {
        client.get().uri("/api/v1/products").header("X-Request-Id", "fe-7f3a").exchange()
                .expectHeader().valueEquals("X-Request-Id", "fe-7f3a");

        String replaced = client.get().uri("/api/v1/products").header("X-Request-Id", "bad id; x=1").exchange()
                .returnResult(String.class).getResponseHeaders().getFirst("X-Request-Id");
        assertThat(replaced).matches("[0-9a-f-]{36}");
    }

    @Test
    void 서비스에_닿지_못하면_503과_오류_본문을_준다() {
        client.post().uri("/api/v1/orders").contentType(MediaType.APPLICATION_JSON).bodyValue("{}").exchange()
                .expectStatus().isEqualTo(503)
                .expectBody().jsonPath("$.code").isEqualTo("SERVICE_UNAVAILABLE");
    }

    @Test
    void 시간_제한을_넘기면_기다리지_않고_503을_준다() {
        long started = System.nanoTime();

        client.get().uri("/api/v1/products/slow").exchange()
                .expectStatus().isEqualTo(503)
                .expectBody().jsonPath("$.code").isEqualTo("SERVICE_UNAVAILABLE");

        assertThat((System.nanoTime() - started) / 1_000_000).isLessThan(2500);
    }

    @Test
    void 서비스가_보낸_오류_응답은_그대로_통과시킨다() {
        client.get().uri("/api/v1/products/busy").exchange()
                .expectStatus().isEqualTo(503)
                .expectBody().jsonPath("$.code").isEqualTo("LOCK_TIMEOUT");
    }

    @Test
    void 실패가_이어지면_회로를_열어_서비스를_부르지_않는다() {
        for (int i = 0; i < 5; i++) {
            client.get().uri("/api/v1/inventories/1/options").exchange().expectStatus().isEqualTo(503);
        }

        assertThat(circuitBreakers.circuitBreaker("order").getState()).isEqualTo(CircuitBreaker.State.OPEN);
    }

    @Test
    void internal_경로는_넘기지_않는다() {
        client.post().uri("/internal/products/load").contentType(MediaType.APPLICATION_JSON).bodyValue("{}")
                .exchange()
                .expectStatus().isNotFound();
    }
}
