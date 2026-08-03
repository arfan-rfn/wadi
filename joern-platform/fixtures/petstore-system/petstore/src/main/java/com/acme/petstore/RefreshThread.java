package com.acme.petstore;

import org.springframework.web.client.RestTemplate;

/**
 * T4 fixture (P8, §5.4.2): a NAMED class behind an external supertype — the
 * upstream-TrainTicket PollThread idiom. Reachable code does
 * `new RefreshThread(rt).start()`; `run()` dispatches through
 * java.lang.Thread and is invisible to call-edge BFS. The constructed-class
 * rule roots the override surface.
 */
public class RefreshThread extends Thread {

    private final RestTemplate restTemplate;

    public RefreshThread(RestTemplate restTemplate) {
        this.restTemplate = restTemplate;
    }

    @Override
    public void run() {
        restTemplate.getForObject("http://inventory:8081/stock/14", Integer.class);
    }
}
