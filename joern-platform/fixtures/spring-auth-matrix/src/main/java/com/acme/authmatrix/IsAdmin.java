package com.acme.authmatrix;

import java.lang.annotation.ElementType;
import java.lang.annotation.Retention;
import java.lang.annotation.RetentionPolicy;
import java.lang.annotation.Target;
import org.springframework.security.access.prepost.PreAuthorize;

/**
 * A composed (meta) annotation — the standard way a mature codebase spells its
 * policy once and reuses it (§5.2.9 D7). Matching security annotations by name
 * alone sees `@IsAdmin` and finds nothing, so the endpoint reads as ungoverned.
 */
@Target({ ElementType.METHOD, ElementType.TYPE })
@Retention(RetentionPolicy.RUNTIME)
@PreAuthorize("hasRole('ADMIN')")
public @interface IsAdmin {
}
