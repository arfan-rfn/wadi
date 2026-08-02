package com.acme.petstore;

public interface PetService {
    String findPet(String id);

    String listPets(String owner);
}
