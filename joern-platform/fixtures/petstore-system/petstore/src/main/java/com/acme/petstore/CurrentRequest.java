package com.acme.petstore;

/** Placeholder for request-scoped token access (keeps the fixture tiny). */
public final class CurrentRequest {

    private CurrentRequest() {}

    public static String bearerToken() {
        return "Bearer token";
    }
}
