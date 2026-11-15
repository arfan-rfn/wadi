package com.acme.crud.service;

import com.acme.crud.domain.Order;
import org.springframework.data.repository.CrudRepository;
import org.springframework.stereotype.Service;

/** Receivers declared as a Spring Data interface itself, not a project
 *  repository: still repository calls, with the entity from the declared
 *  type argument (review A2). */
@Service
public class MarkerTypedOrders {

    private final CrudRepository<Order, String> orders;

    public MarkerTypedOrders(CrudRepository<Order, String> orders) {
        this.orders = orders;
    }

    public long countOrders() {
        return orders.count();
    }

    public boolean exists(String id) {
        return existsIn(orders, id);
    }

    private boolean existsIn(CrudRepository<Order, String> repository, String id) {
        return repository.existsById(id);
    }
}
