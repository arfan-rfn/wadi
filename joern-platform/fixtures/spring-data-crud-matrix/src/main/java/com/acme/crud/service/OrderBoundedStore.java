package com.acme.crud.service;

import com.acme.crud.repo.OrderRepository;
import org.springframework.stereotype.Service;

@Service
public class OrderBoundedStore extends BoundedStore<OrderRepository> {

    public OrderBoundedStore(OrderRepository repository) {
        super(repository);
    }
}
