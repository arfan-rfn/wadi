package com.acme.petstore;

import org.springframework.stereotype.Service;
import org.springframework.web.client.RestTemplate;

/** The concrete leaf of the hierarchy chain (P8 fixture, §5.2.6). */
@Service
public class StatsServiceImpl extends AbstractStatsService {

    public StatsServiceImpl(RestTemplate restTemplate) {
        super(restTemplate);
    }

    @Override
    protected String report(String owner) {
        return restTemplate.postForObject(
                "https://audit.example.com/reports/" + owner, owner, String.class);
    }
}
