package com.acme.greet;

import lombok.RequiredArgsConstructor;
import org.springframework.stereotype.Service;
import org.springframework.web.client.RestTemplate;

@Service
@RequiredArgsConstructor
public class GreetingServiceImpl implements GreetingService {

    private final UpstreamConfig upstreamConfig;
    private final RestTemplate restTemplate;

    @Override
    public String greet(String name) {
        // URL carried through a Lombok-generated getter: the slicer's bridge
        // reads the backing field's source-visible initializer.
        String upstream =
                restTemplate.getForObject(upstreamConfig.getBaseUrl() + "/greet/" + name, String.class);
        return "hello " + name + " (" + upstream + ")";
    }
}
