package com.acme.authmatrix;

import java.lang.annotation.ElementType;
import java.lang.annotation.Retention;
import java.lang.annotation.RetentionPolicy;
import java.lang.annotation.Target;

/**
 * The negative control for §5.2.12: a project-defined annotation consumed by
 * an aspect that does NOT gate.
 *
 * <p>Structurally indistinguishable from {@link TenantAdmin} — same
 * declaration, same {@code @annotation(...)} binding, applied to the same
 * controllers. Only the advice body differs. A rule that treats "an aspect
 * reads it" as "it guards requests" would withhold auth claims across every
 * system that traces, times or audits by annotation, which is most of them;
 * train-ticket's {@code ms-monitoring-core} alone would take the whole corpus
 * down with {@code @NewSpan}.
 */
@Target({ ElementType.METHOD, ElementType.TYPE })
@Retention(RetentionPolicy.RUNTIME)
public @interface Traced {
}
