package com.acme.pets;

public interface PetService {
    Pet findPet(String id);

    Pet createPet(Pet pet);
}
