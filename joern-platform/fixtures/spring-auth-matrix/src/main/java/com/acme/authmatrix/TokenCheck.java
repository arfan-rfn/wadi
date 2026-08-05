package com.acme.authmatrix;

/** A hand-rolled permission decision — the kind of helper an in-handler guard
 *  calls. Its NAME is what marks the call site as a decision; what it permits
 *  is deliberately not interpreted (§5.2.9). */
final class TokenCheck {

    private TokenCheck() {
    }

    static boolean isAuthorized(String apiKey) {
        return apiKey != null && apiKey.startsWith("live_");
    }
}
