package com.acme.authmatrix;

import org.springframework.http.HttpHeaders;
import org.springframework.web.bind.annotation.DeleteMapping;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.PutMapping;
import org.springframework.web.bind.annotation.RequestHeader;
import org.springframework.web.bind.annotation.RestController;

/**
 * The endpoints the filter-chain rules in {@link SecurityConfig} are matched
 * against. Verbs are spread deliberately: the verb-leak defect (§5.2.9 D1)
 * only shows up when one chain carries several verb-scoped matchers AND
 * endpoints that use the other verbs.
 */
@RestController
public class OrderController {

    /** Covered by the POST rule, whose pattern is a bare constant (D2). */
    @PostMapping("/api/v1/orders")
    public String create(@RequestHeader HttpHeaders headers) {
        return "created";
    }

    /** Covered by the PUT rule — a DIFFERENT verb than the chain's first. */
    @PutMapping("/api/v1/orders")
    public String update(@RequestHeader HttpHeaders headers) {
        return "updated";
    }

    /** Covered by the DELETE rule, whose pattern has a trailing wildcard. */
    @DeleteMapping("/api/v1/orders/{orderId}")
    public String remove(@PathVariable String orderId) {
        return "removed";
    }

    /** Matches no verb-scoped rule; falls through to the permitAll sweep. */
    @GetMapping("/api/v1/orders/{orderId}")
    public String read(@PathVariable String orderId) {
        return "order";
    }

    /** Outside every explicit pattern — reaches anyRequest().authenticated(). */
    @GetMapping("/internal/health")
    public String health() {
        return "ok";
    }

    /** Governed by a rule whose pattern cannot be read at all (D2, opaque). */
    @GetMapping("/api/v1/reports")
    public String reports() {
        return "reports";
    }

    /**
     * The guard is written inline, in the handler itself (§5.2.9 D9) — no
     * annotation, no chain rule, nothing the other passes can see. The chain's
     * permitAll sweep covers this path, so without detecting the check the
     * endpoint reads as evidenced-open when it is anything but.
     */
    @GetMapping("/api/v1/orders/export")
    public String export(@RequestHeader HttpHeaders headers) {
        if (!TokenCheck.isAuthorized(headers.getFirst("X-Api-Key"))) {
            throw new IllegalStateException("403");
        }
        return "export";
    }

    /**
     * Behind {@code denyAll()} — reachable by nobody, authenticated or not.
     *
     * <p>The claim rule buckets every non-permissive effect together, so
     * without a distinct state this route publishes as an ordinary protected
     * endpoint and an auditor counts a dead route as live surface (§12).</p>
     */
    @GetMapping("/api/v1/orders/legacy")
    public String legacy() {
        return "legacy";
    }
}
