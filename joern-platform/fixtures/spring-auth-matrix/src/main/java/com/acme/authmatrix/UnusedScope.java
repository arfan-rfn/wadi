package com.acme.authmatrix;

import java.lang.annotation.ElementType;
import java.lang.annotation.Retention;
import java.lang.annotation.RetentionPolicy;
import java.lang.annotation.Target;

/**
 * Declared, bound by an aspect, and applied to NOTHING (§5.2.12).
 *
 * <p>ICPC ships exactly this — its {@code @ACL} annotation has an authorizer
 * and zero call sites — and it is the case that decides whether the tranche
 * helps or hurts. A vocabulary test written against annotation USAGE finds no
 * {@code @UnusedScope} anywhere, concludes the aspect is not annotation-bound,
 * sends it down the {@code execution(...)} path and emits a service-wide
 * {@code {?}}. That one record withheld all 804 ICPC endpoints in the first
 * acceptance run, turning a precise result into a wall of unknowns.
 *
 * <p>An aspect bound to an annotation nobody uses gates nothing, and the
 * honest output is silence.
 */
@Target({ ElementType.METHOD, ElementType.TYPE })
@Retention(RetentionPolicy.RUNTIME)
public @interface UnusedScope {
}
