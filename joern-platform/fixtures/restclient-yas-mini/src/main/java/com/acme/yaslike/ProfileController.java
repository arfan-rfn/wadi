package com.acme.yaslike;

import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RestController;

@RestController
public class ProfileController {

    private final CustomerClient customerClient;

    public ProfileController(CustomerClient customerClient) {
        this.customerClient = customerClient;
    }

    @GetMapping("/profile")
    public String profile() {
        return customerClient.getCustomerProfile();
    }
}
