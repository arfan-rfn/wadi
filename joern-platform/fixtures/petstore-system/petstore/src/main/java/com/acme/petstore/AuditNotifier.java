package com.acme.petstore;

import org.springframework.stereotype.Service;

/**
 * The decoy half of the owner-scoped member fixture (§5.2.5): a same-named
 * field with a different value that must NOT bleed into
 * {@link BillingNotifier}'s slice.
 */
@Service
public class AuditNotifier {

    private String baseUrl = "https://audit.example.com";

    public String target() {
        return baseUrl;
    }
}
