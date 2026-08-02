package com.acme.petstore;

import org.springframework.stereotype.Service;
import org.springframework.web.client.RestTemplate;

/**
 * Owner-scoped member fixture (P8, §5.2.5): this class and
 * {@link AuditNotifier} both declare a field named {@code baseUrl} with
 * different values. The slice of THIS class's field must yield exactly one
 * candidate — the CPG-global name match used to conflate the two into a false
 * multi-assignment fan-out.
 */
@Service
public class BillingNotifier {

    private String baseUrl = "http://billing:9082";

    private final RestTemplate restTemplate;

    public BillingNotifier(RestTemplate restTemplate) {
        this.restTemplate = restTemplate;
    }

    public void report(String owner) {
        restTemplate.postForObject(baseUrl + "/billing-events", owner, String.class);
    }
}
