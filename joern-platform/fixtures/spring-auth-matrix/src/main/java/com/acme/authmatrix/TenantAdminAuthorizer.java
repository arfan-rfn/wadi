package com.acme.authmatrix;

import org.aspectj.lang.ProceedingJoinPoint;
import org.aspectj.lang.annotation.Around;
import org.aspectj.lang.annotation.Aspect;
import org.springframework.stereotype.Component;

/**
 * Gates, and does NOT throw — the shape that defeated the deny-shape predicate
 * (§5.2.12).
 *
 * <p>ICPC's eleven authorizers all look like this: the advice records a verdict
 * on a request-scoped bean and calls {@code proceed()}, and a separate aspect
 * over every controller method turns the accumulated verdict into a 403. The
 * deny is real; it simply is not written here. Scoring this body for
 * {@code SC_FORBIDDEN}/{@code 401}/{@code hasRole} finds nothing — 0 of 8 on
 * the real system.
 *
 * <p>What identifies it is that it reads WHO the caller is and branches on the
 * answer. A guard must know the caller; a tracer need not.
 */
@Aspect
@Component
public class TenantAdminAuthorizer {

    private final PermissionLedger ledger = new PermissionLedger();

    private final TenantDirectory directory = new TenantDirectory();

    @Around(value = "@annotation(tenantAdmin)")
    public Object doAround(ProceedingJoinPoint joinPoint, TenantAdmin tenantAdmin)
            throws Throwable {
        if (directory.isTenantAdmin(directory.getCurrentUserId(), tenantAdmin.scope())) {
            ledger.addSuccess();
        } else {
            ledger.addFailure();
        }
        return joinPoint.proceed();
    }
}

/** The request-scoped verdict a later aspect reads. Deliberately not a throw. */
class PermissionLedger {

    private int failures;

    private int successes;

    void addFailure() {
        this.failures++;
    }

    void addSuccess() {
        this.successes++;
    }

    boolean isAllowed() {
        return this.failures == 0 || this.successes > 0;
    }
}

/** Roles resolved from stored state, not from a token claim. */
class TenantDirectory {

    Long getCurrentUserId() {
        return 1L;
    }

    boolean isTenantAdmin(Long userId, String scope) {
        return userId != null && !scope.isEmpty();
    }
}
