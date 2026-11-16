package com.acme.crud.repo;

import com.acme.crud.domain.OrderLine;
import java.util.List;
import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.data.jpa.repository.Query;

public interface OrderLineRepository extends JpaRepository<OrderLine, Long> {

    @Query("select l from OrderLine l where l.sku = ?1")
    List<OrderLine> findBySkuText(String sku);
}
