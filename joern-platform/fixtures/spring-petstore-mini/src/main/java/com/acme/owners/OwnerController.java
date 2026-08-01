package com.acme.owners;

import java.util.List;

import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RestController;

@RestController
public class OwnerController {

    @GetMapping("/owners")
    public List<String> listOwners() {
        return List.of("alice", "bob");
    }
}
