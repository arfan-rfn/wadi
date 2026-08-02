package com.acme.petstore;

import org.springframework.web.client.RestTemplate;

/**
 * Test-source exclusion fixture (P8, §5.2.6): test code is not production
 * topology. This HTTP call must appear NOWHERE — not as a sink, not in the
 * unreachable inventory, not as a suspected call.
 */
public class PetServiceSmokeTest {

    private final RestTemplate restTemplate = new RestTemplate();

    public void smoke() {
        restTemplate.getForObject("http://test-only-host:1/smoke", String.class);
    }
}
