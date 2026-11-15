package com.acme.crud.repo;

import org.springframework.data.mongodb.repository.MongoRepository;
import org.springframework.data.repository.NoRepositoryBean;

/** A project base whose NAME contains `CrudRepository`, over MongoRepository:
 *  the kind comes from the marker it reaches, not from this name (review A4). */
@NoRepositoryBean
public interface BaseCrudRepository<E> extends MongoRepository<E, String> {
}
