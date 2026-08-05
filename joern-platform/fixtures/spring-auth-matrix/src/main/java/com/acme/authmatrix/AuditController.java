package com.acme.authmatrix;

import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RestController;

/**
 * Annotation-driven authorization (§5.2.9), the half of the space the
 * filter-chain rules do not cover. Note that this fixture's SecurityConfig
 * declares no {@code @EnableMethodSecurity}, so every annotation here is
 * INERT — the worker must mark them inactive rather than report enforcement
 * the running system would not perform (D6).
 */
@RestController
public class AuditController implements AuditApi {

    /** Policy arrives through the composed annotation, not by name (D7). */
    @IsAdmin
    @GetMapping("/api/v1/audit/config")
    public String config() {
        return "config";
    }

    /** Policy arrives through the implemented interface (D7). */
    @Override
    @GetMapping("/api/v1/audit/trail")
    public String trail() {
        return "trail";
    }
}
