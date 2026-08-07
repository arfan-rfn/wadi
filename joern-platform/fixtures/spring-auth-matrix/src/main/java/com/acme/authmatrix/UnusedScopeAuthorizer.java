package com.acme.authmatrix;

import org.aspectj.lang.ProceedingJoinPoint;
import org.aspectj.lang.annotation.Around;
import org.aspectj.lang.annotation.Aspect;
import org.springframework.stereotype.Component;

/**
 * Gates, is annotation-bound, and reaches no endpoint (§5.2.12).
 *
 * <p>Identical to {@link TenantAdminAuthorizer} in every respect that matters
 * to detection — it would pass the gating test on its own — so the only thing
 * keeping it quiet is that {@link UnusedScope} is applied nowhere. Its record
 * in the export must be no record at all.
 */
@Aspect
@Component
public class UnusedScopeAuthorizer {

    private final TenantDirectory directory = new TenantDirectory();

    @Around(value = "@annotation(unusedScope)")
    public Object doAround(ProceedingJoinPoint joinPoint, UnusedScope unusedScope)
            throws Throwable {
        if (this.directory.getCurrentUserId() == null) {
            throw new IllegalStateException("no current user");
        }
        return joinPoint.proceed();
    }

    /**
     * The same aspect binding an annotation declared in a JAR (§5.2.12).
     *
     * <p>{@code com.acme.external.JarScope} is on no CPG — not used anywhere,
     * not declared anywhere readable — which is the ordinary case for a
     * multi-module build, and precisely ICPC's, where the whole vocabulary
     * lives in a sibling artifact. Asking "can I confirm this name is an
     * annotation?" answers no and sends the advice down the
     * {@code execution(...)} path; that emitted one {@code {?}} and withheld
     * all 803 endpoints of the service in the end-to-end run.
     *
     * <p>The designator settles it without resolving anything: {@code
     * @annotation(...)} means the scope is a set of annotated methods. Empty is
     * a fine answer for that set. Service-wide is not.
     */
    @Around(value = "@annotation(com.acme.external.JarScope)")
    public Object doAroundJarBound(ProceedingJoinPoint joinPoint) throws Throwable {
        if (this.directory.getCurrentUserId() == null) {
            throw new IllegalStateException("no current user");
        }
        return joinPoint.proceed();
    }
}
