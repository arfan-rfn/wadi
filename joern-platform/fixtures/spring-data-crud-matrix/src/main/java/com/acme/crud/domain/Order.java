package com.acme.crud.domain;

import jakarta.persistence.Entity;
import jakarta.persistence.Id;
import jakarta.persistence.ManyToOne;
import jakarta.persistence.NamedQuery;
import jakarta.persistence.OneToMany;
import jakarta.persistence.Table;
import java.util.ArrayList;
import java.util.List;

/** An entity named like a SQL keyword. JPQL takes `Order` as an entity name;
 *  the table is renamed because `order` would not survive as SQL. The named
 *  query is resolved by `OrderRepository.shipped` through `@Query(name=...)`. */
@Entity
@Table(name = "orders")
@NamedQuery(name = "Order.findShipped", query = "select o from Order o where o.status = 'SHIPPED'")
public class Order {

    @Id
    private String id;

    private String status;

    @ManyToOne
    private Customer customer;

    @OneToMany(mappedBy = "order")
    private List<OrderLine> lines = new ArrayList<>();

    public Order() {
    }

    public Order(String id) {
        this.id = id;
    }

    public String getId() {
        return id;
    }

    public void setId(String id) {
        this.id = id;
    }

    public String getStatus() {
        return status;
    }

    public void setStatus(String status) {
        this.status = status;
    }

    public Customer getCustomer() {
        return customer;
    }

    public List<OrderLine> getLines() {
        return lines;
    }
}
