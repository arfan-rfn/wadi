package com.acme.petstore;

import org.springframework.boot.ApplicationArguments;
import org.springframework.boot.ApplicationRunner;
import org.springframework.stereotype.Component;
import org.springframework.web.client.RestTemplate;

/**
 * T4 fixture (P8, §5.4.2): a boot runner as a reachability root — detected
 * by implemented interface, not annotation.
 */
@Component
public class WarmupRunner implements ApplicationRunner {

    private final RestTemplate restTemplate;

    public WarmupRunner(RestTemplate restTemplate) {
        this.restTemplate = restTemplate;
    }

    @Override
    public void run(ApplicationArguments args) {
        restTemplate.getForObject("http://inventory:8081/stock/13", Integer.class);
    }
}
