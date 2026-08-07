package com.acme.authmatrix;

import org.aspectj.lang.ProceedingJoinPoint;
import org.aspectj.lang.annotation.Around;
import org.aspectj.lang.annotation.Aspect;
import org.springframework.stereotype.Component;

/**
 * Does NOT gate, and must never be reported as enforcement (§5.2.12).
 *
 * <p>Byte for byte the same binding shape as {@link TenantAdminAuthorizer}: an
 * {@code @Around} advice, an {@code @annotation(...)} designator, a bound
 * annotation parameter, a branch. The only difference is that it never asks
 * who the caller is — which is exactly the discriminator, and the reason this
 * case exists in the fixture rather than in a comment.
 *
 * <p>Without it, a presence-only golden would pass while the feature withheld
 * a claim on every endpoint of every system that traces by annotation.
 */
@Aspect
@Component
public class TracingAspect {

    private final SpanRecorder recorder = new SpanRecorder();

    @Around(value = "@annotation(traced)")
    public Object doAround(ProceedingJoinPoint joinPoint, Traced traced) throws Throwable {
        long startedAt = this.recorder.clock();
        try {
            return joinPoint.proceed();
        } finally {
            if (this.recorder.enabled()) {
                this.recorder.record(joinPoint.getSignature().getName(), startedAt);
            }
        }
    }
}

class SpanRecorder {

    private boolean on = true;

    long clock() {
        return System.nanoTime();
    }

    boolean enabled() {
        return this.on;
    }

    void record(String name, long startedAt) {
        this.on = name != null && startedAt > 0;
    }
}
