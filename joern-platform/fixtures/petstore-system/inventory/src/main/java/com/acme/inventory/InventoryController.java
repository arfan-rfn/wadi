package com.acme.inventory;

import org.springframework.security.access.prepost.PreAuthorize;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.PutMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RestController;

@RestController
public class InventoryController {

    private final StockRepository stockRepository;

    public InventoryController(StockRepository stockRepository) {
        this.stockRepository = stockRepository;
    }

    /** Serves the RestTemplate path (`/stock/{id}`) — public via permitAll. */
    @GetMapping("/stock/{id}")
    public Integer getStock(@PathVariable String id) {
        return stockRepository.countFor(id);
    }

    /** Serves the Feign path. */
    @GetMapping("/api/v1/inventory/stock/{id}")
    public Integer getStockV1(@PathVariable String id) {
        return stockRepository.countFor(id);
    }

    /** Role-protected: annotation evidence for the security pack (M5). */
    @PreAuthorize("hasRole('ADMIN')")
    @PostMapping("/admin/restock")
    public void restock(@RequestBody String payload) {
        stockRepository.restock(payload);
    }

    /** Serves the long-concat exchange() path (T1 §5.2.5 fixture case). */
    @PutMapping("/stock/reserve/{id}/{count}")
    public Integer reserve(@PathVariable String id, @PathVariable String count) {
        return stockRepository.countFor(id);
    }
}
