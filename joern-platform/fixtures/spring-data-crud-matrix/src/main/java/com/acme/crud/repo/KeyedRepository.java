package com.acme.crud.repo;

import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.data.repository.NoRepositoryBean;

/** The key first, the entity second; JpaRepository wants the entity first. */
@NoRepositoryBean
public interface KeyedRepository<ID, E> extends JpaRepository<E, ID> {
}
