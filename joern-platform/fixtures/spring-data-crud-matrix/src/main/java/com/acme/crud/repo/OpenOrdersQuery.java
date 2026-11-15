package com.acme.crud.repo;

import java.lang.annotation.ElementType;
import java.lang.annotation.Retention;
import java.lang.annotation.RetentionPolicy;
import java.lang.annotation.Target;
import org.springframework.data.jpa.repository.Query;

/** A project annotation that carries `@Query` as a meta-annotation: Spring
 *  Data JPA merges it onto the method it annotates (review B1). */
@Target(ElementType.METHOD)
@Retention(RetentionPolicy.RUNTIME)
@Query("select o from Order o where o.status = 'OPEN'")
public @interface OpenOrdersQuery {
}
