package com.capstone.gateway;

import java.util.UUID;
import java.util.regex.Pattern;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.cloud.gateway.filter.GatewayFilterChain;
import org.springframework.cloud.gateway.filter.GlobalFilter;
import org.springframework.core.Ordered;
import org.springframework.http.server.reactive.ServerHttpRequest;
import org.springframework.stereotype.Component;
import org.springframework.web.server.ServerWebExchange;

import reactor.core.publisher.Mono;

/**
 * Gives every routed request an X-Request-Id, sends it to the service and back to the caller, and logs one line per
 * request with it (ADR-133). A caller's own id is kept when it is a plain token, so a chain of calls shares one id;
 * anything else is replaced, as the id ends up in logs.
 */
@Component
class RequestIdFilter implements GlobalFilter, Ordered {

    static final String HEADER = "X-Request-Id";

    private static final Pattern TOKEN = Pattern.compile("[A-Za-z0-9-]{1,64}");
    private static final Logger log = LoggerFactory.getLogger(RequestIdFilter.class);

    @Override
    public Mono<Void> filter(ServerWebExchange exchange, GatewayFilterChain chain) {
        String given = exchange.getRequest().getHeaders().getFirst(HEADER);
        String id = given != null && TOKEN.matcher(given).matches() ? given : UUID.randomUUID().toString();
        ServerHttpRequest request = exchange.getRequest().mutate().headers(headers -> headers.set(HEADER, id)).build();
        exchange.getResponse().getHeaders().set(HEADER, id);
        long started = System.nanoTime();
        return chain.filter(exchange.mutate().request(request).build())
                .doFinally(signal -> log.info("{} {} {} {} {}ms", id, request.getMethod(), request.getPath(),
                        exchange.getResponse().getStatusCode(), (System.nanoTime() - started) / 1_000_000));
    }

    @Override
    public int getOrder() {
        return Ordered.HIGHEST_PRECEDENCE;
    }
}
