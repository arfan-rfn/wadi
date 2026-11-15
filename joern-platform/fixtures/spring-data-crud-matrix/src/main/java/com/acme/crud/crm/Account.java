package com.acme.crud.crm;

import jakarta.persistence.Entity;
import jakarta.persistence.Id;

/** The other `Account` (C2): same simple name, another package. */
@Entity
public class Account {

    @Id
    private Long id;

    private String owner;
}
