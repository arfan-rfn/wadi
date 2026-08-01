package com.acme.greet;

import lombok.RequiredArgsConstructor;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.RestController;

// The dominant modern Spring idiom (§12 risk): the constructor that injects
// greetingService does not exist in the source — Lombok generates it.
@RestController
@RequiredArgsConstructor
public class GreetingController {

    private final GreetingService greetingService;

    @GetMapping("/greet/{name}")
    public String greet(@PathVariable String name) {
        return greetingService.greet(name);
    }
}
