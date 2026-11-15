package com.acme.crud.domain;

import jakarta.persistence.Entity;
import jakarta.persistence.Id;
import jakarta.persistence.NamedQuery;
import jakarta.persistence.Table;

/** The JPQL name differs from the class name: queries say `Client`, and the
 *  implicit named-query key for `CustomerRepository.findVip` is `Client.findVip`. */
@Entity(name = "Client")
@Table(name = "customers")
@NamedQuery(name = "Client.findVip", query = "select c from Client c where c.vip = true")
public class Customer {

    @Id
    private Long id;

    private String email;

    private boolean vip;

    public Long getId() {
        return id;
    }

    public String getEmail() {
        return email;
    }

    public boolean isVip() {
        return vip;
    }
}
