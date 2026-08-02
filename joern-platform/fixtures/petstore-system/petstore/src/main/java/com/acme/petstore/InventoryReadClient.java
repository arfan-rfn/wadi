package com.acme.petstore;

import org.springframework.cloud.openfeign.FeignClient;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;

/**
 * T2 probe (§5.4.2): feign `url = "${key}"` — resolved by template expansion
 * all along, now also surfaced as a config reference (visible to coverage).
 */
@FeignClient(contextId = "inventory-read", name = "inventory-read", url = "${inventory.url}")
public interface InventoryReadClient {

    @GetMapping("/stock/{id}")
    Integer readStock(@PathVariable("id") String id);
}
