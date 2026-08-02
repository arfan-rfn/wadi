package com.acme.petstore;

import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Service;
import org.springframework.web.client.RestClient;

/**
 * T2 probe (§5.4.2): Spring 6.1+ {@code RestClient} — the same fluent shape as
 * WebClient (verb root, then {@code .uri(...)} carrying the URL). This is the
 * yas idiom that used to export as a clean zero-call bill of health.
 */
@Service
public class StockHistoryClient {

    @Value("${inventory.api.url}")
    private String inventoryApiUrl;

    private final RestClient restClient;

    public StockHistoryClient(RestClient restClient) {
        this.restClient = restClient;
    }

    public Integer history(String id) {
        return restClient.get()
                .uri(inventoryApiUrl + "/api/v1/inventory/stock/" + id)
                .retrieve()
                .body(Integer.class);
    }
}
