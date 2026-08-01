package com.acme.pets;

import org.springframework.cloud.openfeign.FeignClient;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;

/**
 * Feign trap (P8 conformance): mapping annotations on a client interface
 * declare OUTBOUND calls — they must never be counted as served endpoints.
 */
@FeignClient(name = "ts-inventory-service")
public interface InventoryClient {

    @GetMapping("/api/v1/inventory/stock/{id}")
    Integer getStock(@PathVariable String id);
}
