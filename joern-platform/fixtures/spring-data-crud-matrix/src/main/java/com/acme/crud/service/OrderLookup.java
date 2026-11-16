package com.acme.crud.service;

import com.acme.crud.repo.OrderRepository;
import org.springframework.stereotype.Service;

@Service
public class OrderLookup {

    private final OrderRepository orderRepository;

    public OrderLookup(OrderRepository orderRepository) {
        this.orderRepository = orderRepository;
    }

    /** The read happens here; the caller sees only the wrapper. */
    public OrderEnvelope loadEnvelope(String id) {
        return new OrderEnvelope(orderRepository.findById(id).orElseThrow());
    }
}
