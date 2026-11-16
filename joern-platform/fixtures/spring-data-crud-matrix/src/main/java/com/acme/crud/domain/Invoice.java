package com.acme.crud.domain;

import jakarta.persistence.Entity;
import jakarta.persistence.Id;
import jakarta.persistence.ManyToOne;
import jakarta.persistence.NamedNativeQuery;
import jakarta.persistence.Table;
import java.math.BigDecimal;

/** Carries a named NATIVE query, resolved implicitly by `InvoiceRepository.sumOpen`. */
@Entity
@Table(name = "invoices")
@NamedNativeQuery(name = "Invoice.sumOpen", query = "select sum(amount) from invoices where paid = false")
public class Invoice {

    @Id
    private Long id;

    private BigDecimal amount;

    private boolean paid;

    @ManyToOne
    private Customer customer;

    public BigDecimal getAmount() {
        return amount;
    }
}
