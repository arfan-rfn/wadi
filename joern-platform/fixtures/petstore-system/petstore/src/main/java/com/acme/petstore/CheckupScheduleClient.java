package com.acme.petstore;

import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Service;
import org.springframework.web.client.RestTemplate;
import org.springframework.web.util.UriComponentsBuilder;

/**
 * T2 probe (§5.4.2): UriComponentsBuilder — the top real-world URL idiom after
 * plain {@code +} concatenation, and a recorded regression vs. the predecessor
 * study. The chain resolves base + path steps; queryParam never affects
 * endpoint identity.
 */
@Service
public class CheckupScheduleClient {

    @Value("${inventory.api.url}")
    private String inventoryApiUrl;

    private final RestTemplate restTemplate;

    public CheckupScheduleClient(RestTemplate restTemplate) {
        this.restTemplate = restTemplate;
    }

    public String nextCheckup(String petId) {
        String url = UriComponentsBuilder.fromHttpUrl(inventoryApiUrl)
                .path("/stock/")
                .path(petId)
                .queryParam("detail", "full")
                .toUriString();
        return restTemplate.getForObject(url, String.class);
    }
}
