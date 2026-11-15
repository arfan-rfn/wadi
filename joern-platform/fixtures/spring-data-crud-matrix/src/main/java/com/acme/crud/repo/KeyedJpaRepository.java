package com.acme.crud.repo;

import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.data.repository.NoRepositoryBean;

/** A project base whose NAME contains `JpaRepository`, with the key first.
 *  It is not a marker: the entity binds through it by position (review A4). */
@NoRepositoryBean
public interface KeyedJpaRepository<ID, E> extends JpaRepository<E, ID> {
}
