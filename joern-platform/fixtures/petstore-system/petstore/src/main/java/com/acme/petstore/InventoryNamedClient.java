package com.acme.petstore;

import org.springframework.cloud.openfeign.FeignClient;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;

/**
 * T2 probe (§5.4.2): non-literal feign name (a static-final constant, resolved
 * in-CPG) + contextId (bean identity only — never names the target).
 */
@FeignClient(contextId = "inventory-audit", name = ApiPaths.INVENTORY_NAME, path = "/api/v1/inventory")
public interface InventoryNamedClient {

    @GetMapping("/audit/{id}")
    Integer audit(@PathVariable("id") String id);
}
