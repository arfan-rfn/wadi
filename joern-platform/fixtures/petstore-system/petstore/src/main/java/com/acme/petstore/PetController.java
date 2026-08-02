package com.acme.petstore;

import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.PutMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

@RestController
@RequestMapping("/pets")
public class PetController {

    private final PetService petService;

    public PetController(PetService petService) {
        this.petService = petService;
    }

    @GetMapping("/{id}")
    public String getPet(@PathVariable String id) {
        return petService.findPet(id);
    }

    @GetMapping
    public String listPets(@RequestParam(required = false) String owner) {
        return petService.listPets(owner);
    }

    @PutMapping("/{id}/reserve/{count}")
    public String reserve(@PathVariable String id, @PathVariable String count) {
        return petService.reserveStock(id, count);
    }

    @PostMapping("/{id}/alert")
    public String alert(@PathVariable String id) {
        return petService.stockAlert(id);
    }

    @GetMapping("/summary/{id}")
    public String summary(@PathVariable String id) {
        com.acme.common.StockQuery query = new com.acme.common.StockQuery();
        query.setId(id);
        return petService.stockSummary(query);
    }
}
