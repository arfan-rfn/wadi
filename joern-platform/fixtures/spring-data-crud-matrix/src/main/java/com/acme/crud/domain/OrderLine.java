package com.acme.crud.domain;

import jakarta.persistence.Entity;
import jakarta.persistence.Id;
import jakarta.persistence.ManyToOne;

/** No @Table: the storage name stays null. The join target of `o.lines`. */
@Entity
public class OrderLine {

    @Id
    private Long id;

    private String sku;

    @ManyToOne
    private Order order;

    public String getSku() {
        return sku;
    }

    public Order getOrder() {
        return order;
    }
}
