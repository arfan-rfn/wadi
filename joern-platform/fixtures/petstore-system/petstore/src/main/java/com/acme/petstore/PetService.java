package com.acme.petstore;

import com.acme.common.StockQuery;

public interface PetService {
    String findPet(String id);

    String listPets(String owner);

    String reserveStock(String id, String count);

    String stockAlert(String id);

    String stockSummary(StockQuery query);
}
