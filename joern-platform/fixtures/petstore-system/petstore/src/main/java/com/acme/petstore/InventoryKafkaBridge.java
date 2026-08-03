package com.acme.petstore;

import org.springframework.kafka.annotation.KafkaListener;
import org.springframework.stereotype.Component;
import org.springframework.web.client.RestTemplate;

/**
 * T4 fixture (P8, §5.4.2): a message listener as a reachability root. Only
 * the ROOT semantics are T4's job — publish/consume topology stays with the
 * Phase 3 MQ packs.
 */
@Component
public class InventoryKafkaBridge {

    private final RestTemplate restTemplate;

    public InventoryKafkaBridge(RestTemplate restTemplate) {
        this.restTemplate = restTemplate;
    }

    @KafkaListener(topics = "restock-requests")
    public void onMessage(String payload) {
        restTemplate.getForObject("http://inventory:8081/stock/12", Integer.class);
    }
}
