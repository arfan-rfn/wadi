package com.acme.crud.service;

import com.acme.crud.repo.BaseRepository;

/** The receiver is declared as the generic base interface itself, so `E`
 *  has nothing to bind to: the entity is undetermined (R1-4). */
public abstract class AbstractArchiver<E> {

    private final BaseRepository<E> repository;

    protected AbstractArchiver(BaseRepository<E> repository) {
        this.repository = repository;
    }

    public long countAll() {
        return repository.count();
    }
}
