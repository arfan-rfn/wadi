package com.acme.petstore;

import org.springframework.web.client.RestTemplate;

/**
 * The intermediate abstract base (P8 fixture, §5.2.6): the entry method lives
 * HERE (inherited, not overridden), and the sink lives in the concrete leaf.
 * A flat one-hop DI index used to land the edge on a bodiless stub and
 * dead-end the closure BFS.
 */
public abstract class AbstractStatsService implements StatsService {

    protected final RestTemplate restTemplate;

    protected AbstractStatsService(RestTemplate restTemplate) {
        this.restTemplate = restTemplate;
    }

    @Override
    public String weekly(String owner) {
        return report(owner);
    }

    protected abstract String report(String owner);
}
