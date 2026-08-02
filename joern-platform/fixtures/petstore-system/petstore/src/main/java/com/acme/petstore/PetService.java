package com.acme.petstore;

public interface PetService {
    String findPet(String id);

    String listPets(String owner);

    String reserveStock(String id, String count);

    String stockAlert(String id);
}
