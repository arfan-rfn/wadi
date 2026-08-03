package com.acme.sweeper;

import org.springframework.scheduling.annotation.Scheduled;
import org.springframework.stereotype.Service;
import org.springframework.web.client.RestTemplate;

/**
 * The controller-less service's only flow: a scheduled sweep calling
 * inventory. Before T4 this whole service exported zero methods and zero
 * sinks — indistinguishable from an empty repository.
 */
@Service
public class ExpiredReservationSweeper {

    private final RestTemplate restTemplate;

    public ExpiredReservationSweeper(RestTemplate restTemplate) {
        this.restTemplate = restTemplate;
    }

    @Scheduled(cron = "0 0 3 * * *")
    public void sweepExpired() {
        restTemplate.getForObject("http://inventory:8081/api/v1/inventory/reserved/0", String.class);
    }
}
