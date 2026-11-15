package com.acme.crud.service;

import com.acme.crud.domain.Order;

/** A wrapper a helper returns around a read entity. */
public class OrderEnvelope {

    private final Order order;

    public OrderEnvelope(Order order) {
        this.order = order;
    }

    public Order getOrder() {
        return order;
    }
}
