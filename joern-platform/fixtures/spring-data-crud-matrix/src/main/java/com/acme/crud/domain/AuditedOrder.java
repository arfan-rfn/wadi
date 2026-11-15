package com.acme.crud.domain;

import jakarta.persistence.Entity;
import jakarta.persistence.Id;
import jakarta.persistence.Table;

/** The same table name as `Order`, in another schema: a native query that
 *  names `audit.orders` means this entity and not that one (review B2). */
@Entity
@Table(name = "orders", schema = "audit")
public class AuditedOrder {

    @Id
    private Long id;

    private String status;
}
