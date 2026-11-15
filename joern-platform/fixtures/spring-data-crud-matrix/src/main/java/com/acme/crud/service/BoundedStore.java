package com.acme.crud.service;

import com.acme.crud.domain.Order;
import java.util.List;
import org.springframework.data.jpa.repository.JpaRepository;

/** The receiver is a type variable bounded by a Spring Data interface: the
 *  bound is the repository it is known to be (review A2). */
public abstract class BoundedStore<R extends JpaRepository<Order, String>> {

    private final R repository;

    protected BoundedStore(R repository) {
        this.repository = repository;
    }

    public List<Order> all() {
        return repository.findAll();
    }
}
