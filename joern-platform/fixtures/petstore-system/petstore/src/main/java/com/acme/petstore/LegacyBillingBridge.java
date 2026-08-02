package com.acme.petstore;

import org.springframework.stereotype.Service;

/**
 * Suspected-sink fixture (P8, §5.2.5): {@code BridgeLocator} exists on no
 * classpath and in no source, so the receiver type is unresolvable — exactly
 * the shape that used to vanish without a trace. The HTTP-shaped call name
 * (exchange) must surface as kind {@code http-client-suspected}: a countable
 * maybe, never blended into resolved results (P7).
 */
@Service
public class LegacyBillingBridge {

    public String charge(String owner) {
        var bridge = BridgeLocator.acquire();
        return bridge.exchange("http://billing:9999/charge/" + owner);
    }
}
