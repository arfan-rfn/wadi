package com.acme.pets;

import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.stereotype.Service;
import org.springframework.web.client.RestTemplate;

@Service
public class PetServiceImpl implements PetService {

    @Autowired
    private PetRepository petRepository;

    @Autowired
    private RestTemplate restTemplate;

    private String inventoryUrl = "http://inventory:8080";

    @Override
    public Pet findPet(String id) {
        if (id == null || id.isEmpty()) {
            throw new IllegalArgumentException("id required");
        }
        Pet pet = petRepository.findById(id).orElseThrow();
        Integer stock = restTemplate.getForObject(inventoryUrl + "/stock/" + id, Integer.class);
        if (stock != null) {
            pet.setStockCount(stock.intValue());
        }
        return pet;
    }

    @Override
    public Pet createPet(Pet pet) {
        return petRepository.save(pet);
    }
}
