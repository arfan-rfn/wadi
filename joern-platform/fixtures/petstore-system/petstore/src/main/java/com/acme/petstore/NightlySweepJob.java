package com.acme.petstore;

import java.util.concurrent.CompletableFuture;

import com.acme.notonclasspath.ExternalMetrics;
import org.springframework.scheduling.annotation.Scheduled;
import org.springframework.stereotype.Service;
import org.springframework.web.client.RestTemplate;

/**
 * T4 fixture (P8, §5.4.2): a scheduled job is a reachability ROOT — no
 * controller reaches this class, yet every sink below is live code. Each
 * method exercises one T4 traversal edge with its own target URL so the
 * conformance test can assert per-construct:
 *
 *   sweep()        — the async root itself (direct sink, /stock/9)
 *   lambda         — METHOD_REF-bound lambda body (/stock/10)
 *   this::refresh  — method reference (/api/v1/inventory/reserved/3)
 *   new Runnable() — anonymous class body (/api/v1/inventory/audit/7)
 *   RefreshThread  — named class behind external Thread (/stock/14)
 *   constructor    — DI-bean ctor body, never `new`ed in user code (/stock/8)
 */
@Service
public class NightlySweepJob {

    private final RestTemplate restTemplate;

    public NightlySweepJob(RestTemplate restTemplate) {
        this.restTemplate = restTemplate;
        restTemplate.getForObject("http://inventory:8081/stock/8", Integer.class);
    }

    @Scheduled(fixedRate = 60000)
    public void sweep() {
        restTemplate.getForObject("http://inventory:8081/stock/9", Integer.class);
        CompletableFuture.runAsync(
                () -> restTemplate.getForObject("http://inventory:8081/stock/10", Integer.class));
        CompletableFuture.runAsync(this::refreshReserved);
        // Regression trap (benchmark-proven): a method ref on a type the CPG
        // cannot resolve has NO REF edge — the closure walk must skip it,
        // never throw (the strict accessor crashed 34 benchmark services).
        CompletableFuture.runAsync(ExternalMetrics::flush);
        new RefreshThread(restTemplate).start();
        Runnable audit = new Runnable() {
            @Override
            public void run() {
                restTemplate.getForObject(
                        "http://inventory:8081/api/v1/inventory/audit/7", String.class);
            }
        };
        audit.run();
    }

    private void refreshReserved() {
        restTemplate.getForObject("http://inventory:8081/api/v1/inventory/reserved/3", String.class);
    }
}
