package com.acme.inventory;

import org.springframework.stereotype.Component;

@Component
public class StockRepository {

    public Integer countFor(String id) {
        return id.length();
    }

    public void restock(String payload) {
        // fixture stub
    }
}
