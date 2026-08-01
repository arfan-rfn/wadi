package com.acme.pets;

import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

@RestController
@RequestMapping("/pets")
public class PetController {

    @Autowired
    private PetService petService;

    @GetMapping("/{id}")
    public Pet getPet(@PathVariable String id) {
        return petService.findPet(id);
    }

    @PostMapping("")
    public Pet createPet(@RequestBody Pet pet) {
        return petService.createPet(pet);
    }
}
