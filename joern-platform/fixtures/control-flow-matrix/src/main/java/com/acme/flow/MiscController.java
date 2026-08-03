package com.acme.flow;

import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.RestController;

/** Remaining constructs: synchronized, multiple returns, empty body. */
@RestController
public class MiscController {

    private final Object lock = new Object();
    private int hits;

    @GetMapping("/misc/synchronized/{n}")
    public String synchronizedBlock(@PathVariable int n) {
        synchronized (lock) {
            hits += n;
        }
        return String.valueOf(hits);
    }

    @GetMapping("/misc/multi-return/{n}")
    public String multiReturn(@PathVariable int n) {
        if (n == 0) {
            return "zero";
        }
        if (n < 0) {
            return "negative";
        }
        return "positive";
    }

    @GetMapping("/misc/empty")
    public void emptyBody() {
    }
}
