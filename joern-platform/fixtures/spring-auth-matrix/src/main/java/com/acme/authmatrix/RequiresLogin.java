package com.acme.authmatrix;

import java.lang.annotation.ElementType;
import java.lang.annotation.Retention;
import java.lang.annotation.RetentionPolicy;
import java.lang.annotation.Target;

/**
 * The interceptor-bound half of the §5.2.12 derivation rule.
 *
 * <p>No AspectJ anywhere: a plain Spring MVC {@code HandlerInterceptor} reads
 * this annotation off the handler with {@code getMethodAnnotation}. It is the
 * commonest hand-rolled auth idiom in Spring codebases, and it binds by a
 * reflective READ rather than by a pointcut — so it exercises the one
 * derivation route the aspect cases never touch.
 */
@Target({ ElementType.METHOD, ElementType.TYPE })
@Retention(RetentionPolicy.RUNTIME)
public @interface RequiresLogin {
}
