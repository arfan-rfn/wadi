package com.acme.petstore;

import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

/** Nested-class constant prefix (P8 fixture, §5.4.2 — yas location shape). */
@RestController
@RequestMapping(ApiPaths.Nested.VET_PETS)
public class VetPetController {

    @GetMapping("/checkups")
    public String checkups() {
        return "ok";
    }
}
