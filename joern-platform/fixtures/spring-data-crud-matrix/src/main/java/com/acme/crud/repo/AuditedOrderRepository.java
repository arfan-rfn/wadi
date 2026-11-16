package com.acme.crud.repo;

import com.acme.crud.domain.AuditedOrder;
import java.util.List;
import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.data.jpa.repository.Query;

public interface AuditedOrderRepository extends JpaRepository<AuditedOrder, Long> {

    @Query(value = "select * from audit.orders where status = ?1", nativeQuery = true)
    List<AuditedOrder> findAuditedByStatus(String status);
}
