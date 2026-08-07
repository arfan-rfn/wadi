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

    /** Guarded by a project-defined vocabulary: withheld, exact scope. */
    @TenantAdmin(scope = "billing")
    @GetMapping("/api/v1/tenant/settings")
    public String settings() {
        return "settings";
    }

    /** Same binding shape, non-gating advice: the claim must SURVIVE. */
    @Traced
    @GetMapping("/api/v1/tenant/activity")
    public String activity() {
        return "activity";
    }

    /** Neither: the control that proves scoping is per-endpoint. */
    @GetMapping("/api/v1/tenant/status")
    public String status() {
        return "status";
    }
}
