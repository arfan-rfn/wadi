package com.acme.crud.repo;

import com.acme.crud.domain.Customer;
import java.util.List;
import org.springframework.data.jpa.repository.JpaRepository;

public interface CustomerRepository extends JpaRepository<Customer, Long> {

    /** No annotation: resolves to the implicit named query `Client.findVip`,
     *  keyed by the JPQL name and not the class name. */
    List<Customer> findVip();
}
