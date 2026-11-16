package com.acme.crud.repo;

import com.acme.crud.domain.Invoice;
import java.math.BigDecimal;
import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.data.jpa.repository.Modifying;
import org.springframework.data.jpa.repository.Query;

public interface InvoiceRepository extends JpaRepository<Invoice, Long> {

    /** Deletes Invoice, reads Customer (by its JPQL name `Client`): one site,
     *  two accesses (C1). */
    @Modifying
    @Query("delete from Invoice i where i.customer in (select c from Client c where c.vip = false)")
    int deleteForNonVip();

    /** No annotation: resolves to the implicit `@NamedNativeQuery` `Invoice.sumOpen`. */
    BigDecimal sumOpen();
}
