package com.acme.crud.service;

import com.acme.crud.domain.Order;
import com.acme.crud.repo.OrderRepository;
import org.springframework.stereotype.Service;

/** Saves of a method parameter: the origin is one caller hop away (R1-27).
 *  One method per golden, so each golden's call closure is its own. */
@Service
public class OrderWriter {

    private final OrderRepository orderRepository;

    public OrderWriter(OrderRepository orderRepository) {
        this.orderRepository = orderRepository;
    }

    /** Every caller passes an object it read. */
    public Order storeAgreed(Order order) {
        return orderRepository.save(order);
    }

    /** One caller passes a read object, the other a new one. */
    public Order storeDisagreed(Order order) {
        return orderRepository.save(order);
    }

    /** The caller passes its own @RequestBody parameter: still a parameter after one hop. */
    public Order storeBody(Order order) {
        return orderRepository.save(order);
    }
}
