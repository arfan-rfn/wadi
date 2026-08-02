package com.acme.petstore;

import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

/**
 * P8 fixture (§5.4.2 endpoint idioms): the class prefix is a static-final
 * CONSTANT (not a string literal), and the mapping declares TWO paths — one
 * endpoint per array entry. Both idioms are yas ground truth.
 */
@RestController
@RequestMapping(ApiPaths.ADMIN_PETS)
public class AdminPetController {

    @GetMapping({"/summary", "/report"})
    public String overview() {
        return "ok";
    }
}
