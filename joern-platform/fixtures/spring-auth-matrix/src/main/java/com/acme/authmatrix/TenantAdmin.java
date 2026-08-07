package com.acme.authmatrix;

import java.lang.annotation.ElementType;
import java.lang.annotation.Retention;
import java.lang.annotation.RetentionPolicy;
import java.lang.annotation.Target;

/**
 * A project-defined authorization vocabulary (§5.2.12).
 *
 * <p>Nothing here is a Spring or JSR-250 name, and it does not compose from
 * one either — so the annotation pass, which matches names and follows
 * meta-annotations only until they bottom out in a name it knows, sees
 * nothing. This is not exotic: it is what every codebase that spells its own
 * policy looks like, and on ICPC it governs 637 of 803 handlers.
 *
 * <p>What makes it readable is not the name but the BINDING — the advice
 * parameter type in {@link TenantAdminAuthorizer}, which is a graph property
 * no vocabulary list is needed to see.
 */
@Target({ ElementType.METHOD, ElementType.TYPE })
@Retention(RetentionPolicy.RUNTIME)
public @interface TenantAdmin {

    /** Policy detail carried as an argument, the shape ICPC uses throughout. */
    String scope() default "";
}
