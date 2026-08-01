package com.acme.pets;

import org.springframework.data.annotation.Id;
import org.springframework.data.mongodb.core.mapping.Document;

@Document("pets")
public class Pet {
    @Id
    private String id;
    private String name;
    private int stockCount;

    public String getId() {
        return id;
    }

    public String getName() {
        return name;
    }

    public int getStockCount() {
        return stockCount;
    }

    public void setStockCount(int stockCount) {
        this.stockCount = stockCount;
    }
}
