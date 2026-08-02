package com.acme.petstore;

import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Service;
import org.springframework.web.client.RestClient;
import org.springframework.web.reactive.function.client.WebClient;

/**
 * T2 probes (§5.4.2): the rootUri/baseUrl split. `bound` carries a
 * statically-visible base (recovered and prepended); `injected` does not —
 * its relative path reports base-undetermined, never a fabricated absolute.
 */
@Service
public class BaseBoundClient {

    @Value("${inventory.api.url}")
    private String inventoryApiUrl;

    private final RestClient bound;
    private final WebClient injected;

    public BaseBoundClient(WebClient injected) {
        this.bound = RestClient.create(inventoryApiUrl);
        this.injected = injected;
    }

    public Integer boundStock(String id) {
        return bound.get().uri("/stock/" + id).retrieve().body(Integer.class);
    }

    public String unresolvableBase(String id) {
        return injected.get().uri("/mystery/" + id).retrieve().bodyToMono(String.class).block();
    }
}
