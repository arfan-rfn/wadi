package com.acme.orders;

import org.springframework.data.repository.CrudRepository;

/**
 * `save` is declared by the EXTERNAL CrudRepository supertype, not here, so a
 * call to it names a first-party type but has no first-party body: the honest
 * reason is `inherited-external`. `findByStatus` IS declared here (and, being
 * a Spring Data derived query, has no body either — but that is an interface
 * declaration, which the CFG reports as an empty body rather than a gap).
 */
public interface OrderRepository extends CrudRepository<Order, String> {

    Order findByStatus(String status);
}
