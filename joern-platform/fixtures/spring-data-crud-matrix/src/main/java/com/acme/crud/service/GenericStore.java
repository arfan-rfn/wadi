package com.acme.crud.service;

import java.util.List;
import org.springframework.data.jpa.repository.JpaRepository;

/** A generic base service holding the marker interface itself: the type
 *  argument is the class's own `E`, so the entity is undetermined (review A2). */
public abstract class GenericStore<E> {

    protected JpaRepository<E, Long> repository;

    public List<E> all() {
        return repository.findAll();
    }
}
