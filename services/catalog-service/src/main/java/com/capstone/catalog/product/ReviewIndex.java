package com.capstone.catalog.product;

import java.time.Duration;
import java.util.Map;

import org.springframework.beans.factory.annotation.Value;
import org.springframework.http.MediaType;
import org.springframework.http.client.SimpleClientHttpRequestFactory;
import org.springframework.stereotype.Component;
import org.springframework.web.client.RestClient;

/** The OpenSearch review documents, each carrying a copy of its product's fields (ADR-102). */
@Component
public class ReviewIndex {

    private final RestClient client;
    private final String index;

    public ReviewIndex(@Value("${catalog.opensearch.url}") String url,
                       @Value("${catalog.opensearch.index}") String index,
                       @Value("${catalog.opensearch.timeout-millis}") int timeoutMillis) {
        SimpleClientHttpRequestFactory factory = new SimpleClientHttpRequestFactory();
        factory.setConnectTimeout(Duration.ofMillis(timeoutMillis));
        factory.setReadTimeout(Duration.ofMillis(timeoutMillis));
        this.client = RestClient.builder().baseUrl(url).requestFactory(factory).build();
        this.index = index;
    }

    /**
     * Rewrites the price on every review document of the product and refreshes, so search sees it on return. A version
     * conflict fails the call instead of skipping documents.
     */
    public void updatePrice(long productId, int price) {
        client.post()
                .uri("/{index}/_update_by_query?refresh=true", index)
                .contentType(MediaType.APPLICATION_JSON)
                .body(Map.of("query", Map.of("term", Map.of("product_id", productId)),
                             "script", Map.of("source", "ctx._source.price = params.price",
                                              "params", Map.of("price", price))))
                .retrieve()
                .toBodilessEntity();
    }
}
