package com.acme.sweeper;

import org.springframework.boot.SpringApplication;
import org.springframework.boot.autoconfigure.SpringBootApplication;
import org.springframework.scheduling.annotation.EnableScheduling;

/**
 * T4 fixture (P8, §5.4.2): a CONTROLLER-LESS service — the recorded answer to
 * the zero-export question. No endpoints exist; the async root below is the
 * only reason this service has methods, sinks, and edges at all.
 */
@SpringBootApplication
@EnableScheduling
public class SweeperApplication {
    public static void main(String[] args) {
        SpringApplication.run(SweeperApplication.class, args);
    }
}
