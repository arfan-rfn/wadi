package com.acme.authmatrix;

import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RestController;

/**
 * The §5.2.12 matrix: three handlers that differ only in which project-defined
 * annotation they carry.
 *
 * <p>All three are structurally identical to the name-matching pass — none
 * carries a Spring or JSR-250 annotation, so all three read as ungoverned
 * today. What must come out is three DIFFERENT answers, and getting two of
 * them right is not a partial success:
 *
 * <ul>
 * <li>{@code /settings} is guarded and its claim must be withheld;
 * <li>{@code /activity} is traced, not guarded, and must keep its claim;
 * <li>{@code /status} carries nothing and must keep its claim.
 * </ul>
 *
 * <p>The last two are what stop the feature from being a blanket. An
 * enforcement scoped to the aspect rather than to the annotated methods would
 * pass a presence-only golden while withholding all three.
 */
@RestController
public class TenantController {

    /**
     * Guarded by a project-defined vocabulary, and READ (§5.2.12 M2).
     *
     * <p>The annotation states its own policy: a relation (from the annotation
     * name), the resource it is required on, and a permission required in
     * addition. None of that is interpretation — it is what the developer
     * wrote — so this publishes a requirement rather than withholding.
     */
    @TenantAdmin(resource = Tenant.class, permissions = Permission.BILLING_WRITE)
    @GetMapping("/api/v1/tenant/settings")
    public String settings() {
        return "settings";
    }

    /**
     * TWO type-valued attributes, so the resource is ambiguous by shape.
     *
     * <p>ICPC writes `@ContestManager(context = Contest.class, entity =
     * Standings.class)`, where the context is the resource and the entity is
     * how it is reached — but nothing in the shape says which is which, and
     * "the first one is the resource" is an invention. The relation is still
     * published; `resource_type` is not, and both types stay visible verbatim
     * in `detail` so the reader sees what was declined rather than a confident
     * half-answer (P10).
     */
    @TenantAdmin(resource = Tenant.class, via = Membership.class,
            permissions = Permission.TENANT_DELETE)
    @GetMapping("/api/v1/tenant/members")
    public String members() {
        return "members";
    }

    /** Same binding shape, non-gating advice: the claim must SURVIVE. */
    @Traced
    @GetMapping("/api/v1/tenant/activity")
    public String activity() {
        return "activity";
    }

    /**
     * Guarded by an INTERCEPTOR that reads the annotation (§5.2.12 route c).
     *
     * <p>No AspectJ involved, and the interceptor is registered on
     * {@code /**} — so its real scope is this handler alone, and reporting
     * its registration scope would withhold the whole service.
     */
    @RequiresLogin
    @GetMapping("/api/v1/tenant/audit")
    public String audit() {
        return "audit";
    }

    /** Neither: the control that proves scoping is per-endpoint. */
    @GetMapping("/api/v1/tenant/status")
    public String status() {
        return "status";
    }
}
