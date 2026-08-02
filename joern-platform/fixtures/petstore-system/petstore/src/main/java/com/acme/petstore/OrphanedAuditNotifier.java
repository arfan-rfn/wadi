package com.acme.petstore;

import org.springframework.stereotype.Service;
import org.springframework.web.client.RestTemplate;

/**
 * Deliberately unwired (P8 fixture, §5.2.5): no controller reaches this class
 * — the TrainTicket repos are full of copy-pasted service classes like it.
 * Its sink must land in the unreachable_sinks inventory, never in the map and
 * never silently dropped.
 */
@Service
public class OrphanedAuditNotifier {

    private final RestTemplate restTemplate;

    public OrphanedAuditNotifier(RestTemplate restTemplate) {
        this.restTemplate = restTemplate;
    }

    public void notifyAudit(String event) {
        restTemplate.postForObject("https://audit.example.com/orphaned/" + event, event, String.class);
    }
}
