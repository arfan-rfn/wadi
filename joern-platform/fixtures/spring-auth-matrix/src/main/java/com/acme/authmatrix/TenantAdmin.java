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
 *
 * <p>The attribute NAMES here (`resource`, `permissions`, `via`) are
 * deliberately not ICPC's (`context`, `acl`, `entity`). The policy is read
 * from the shape of the VALUES — a `Foo.class` names a type, a screaming-snake
 * constant names a permission — because a list of attribute names would be the
 * same closed-vocabulary mistake one level further down.
 */
@Target({ ElementType.METHOD, ElementType.TYPE })
@Retention(RetentionPolicy.RUNTIME)
public @interface TenantAdmin {

    /** The resource the relation is required ON. */
    Class<?> resource() default Object.class;

    /** How the resource is reached — a SECOND type-valued attribute, which is
     *  what makes the resource ambiguous by shape alone. */
    Class<?> via() default Object.class;

    /** Permissions required in addition to the relation. */
    Permission[] permissions() default {};
}
