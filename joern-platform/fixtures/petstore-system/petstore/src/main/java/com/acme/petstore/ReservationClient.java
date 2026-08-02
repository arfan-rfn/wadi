package com.acme.petstore;

import java.net.URI;

import org.springframework.beans.factory.annotation.Value;
import org.springframework.http.RequestEntity;
import org.springframework.stereotype.Service;
import org.springframework.web.client.RestTemplate;

/**
 * T2 probe (§5.4.2): {@code RequestEntity}-form exchange — verb and URL live
 * on the entity's builder chain, off the call site, wrapped in
 * {@code URI.create}. The literal-HttpMethod fallback alone sees neither.
 */
@Service
public class ReservationClient {

    @Value("${inventory.api.url}")
    private String inventoryApiUrl;

    private final RestTemplate restTemplate;

    public ReservationClient(RestTemplate restTemplate) {
        this.restTemplate = restTemplate;
    }

    public Integer reserve(String petId) {
        RequestEntity<Void> request = RequestEntity
                .put(URI.create(inventoryApiUrl + "/stock/reserve/" + petId + "/1"))
                .build();
        return restTemplate.exchange(request, Integer.class).getBody();
    }
}
