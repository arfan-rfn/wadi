package com.acme.crud.billing;

import jakarta.persistence.Entity;
import jakarta.persistence.Id;
import jakarta.persistence.Table;

/** One of two classes named `Account` (C2). JPA needs distinct entity names,
 *  so this one sets `@Entity(name=)`. */
@Entity(name = "BillingAccount")
@Table(name = "billing_accounts")
public class Account {

    @Id
    private Long id;

    private String iban;
}
