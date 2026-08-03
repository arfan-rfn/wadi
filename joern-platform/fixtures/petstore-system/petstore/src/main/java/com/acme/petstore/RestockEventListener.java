package com.acme.petstore;

import org.springframework.context.event.EventListener;
import org.springframework.stereotype.Component;
import org.springframework.web.client.RestTemplate;

/**
 * T4 fixture (P8, §5.4.2): an event listener roots the closure and the BFS
 * continues through its private helpers — the sink lives one hop away from
 * the root, not on it.
 */
@Component
public class RestockEventListener {

    private final RestTemplate restTemplate;

    public RestockEventListener(RestTemplate restTemplate) {
        this.restTemplate = restTemplate;
    }

    @EventListener
    public void onRestock(Object event) {
        record(event);
    }

    private void record(Object event) {
        restTemplate.getForObject("http://inventory:8081/stock/11", Integer.class);
    }
}
