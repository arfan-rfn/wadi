package com.acme.petstore;

import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;

/**
 * T2 probe (§5.4.2): the shared-contract idiom — mapping annotations live on
 * a PARENT interface the feign client extends. Previously produced no sink.
 */
public interface SharedInventoryContract {

    @GetMapping("/api/v1/inventory/reserved/{id}")
    Integer reserved(@PathVariable("id") String id);
}
