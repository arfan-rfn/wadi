package com.acme.petstore;

import org.springframework.stereotype.Component;

/** Simulates runtime-only targets: URLs living in a database row. */
@Component
public class EndpointRegistry {

    public String lookupCallbackUrl(String owner) {
        // In a real system this reads a DB row — statically undeterminable.
        return System.getenv("CALLBACK_" + owner);
    }
}
