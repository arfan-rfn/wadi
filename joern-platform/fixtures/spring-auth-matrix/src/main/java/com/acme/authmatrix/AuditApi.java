package com.acme.authmatrix;

import org.springframework.security.access.annotation.Secured;

/**
 * The shared contract an implementing controller inherits its policy from
 * (§5.2.9 D7). Reading only the controller's own declarations misses this
 * entirely — the handler looks unguarded when the interface guards it.
 *
 * <p>Note the mapping annotation stays on the IMPLEMENTATION here. Mapping
 * annotations inherited from an interface are a separate, recorded gap in
 * endpoint extraction (§5.4.2, not §5.2.9): such an endpoint is not extracted
 * at all today, so pairing the two in one case would hide an auth regression
 * behind an endpoint one.
 */
public interface AuditApi {

    @Secured("ROLE_AUDITOR")
    String trail();
}
