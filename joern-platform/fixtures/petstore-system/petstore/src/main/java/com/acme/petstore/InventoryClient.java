package com.acme.petstore;

import org.springframework.cloud.openfeign.FeignClient;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestMethod;

/** Declares OUTBOUND calls (Feign) — its mappings must never count as served
 * endpoints (the TrainTicket false-positive trap, Phase 1). The Feign sink
 * pass (M5) turns calls to these methods into http-client sinks. */
@FeignClient(name = "inventory")
public interface InventoryClient extends SharedInventoryContract {

    @GetMapping("/api/v1/inventory/stock/{id}")
    Integer getStock(@PathVariable("id") String id);

    /** T2: the RequestMapping(method=…) verb form on a feign method. */
    @RequestMapping(method = RequestMethod.GET, value = "/stock/{id}")
    Integer stockViaRequestMapping(@PathVariable("id") String id);
}
