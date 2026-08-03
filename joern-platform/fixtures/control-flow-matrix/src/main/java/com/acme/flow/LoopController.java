package com.acme.flow;

import java.util.List;
import java.util.concurrent.atomic.AtomicInteger;

import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.RestController;

/** One handler per loop construct, including the statement-level self-loop
 * (empty body) the current projection deletes outright. */
@RestController
public class LoopController {

    @GetMapping("/loop/for/{n}")
    public String classicFor(@PathVariable int n) {
        int sum = 0;
        for (int i = 0; i < n; i++) {
            sum += i;
        }
        return String.valueOf(sum);
    }

    @GetMapping("/loop/foreach/{n}")
    public String enhancedFor(@PathVariable int n) {
        int sum = 0;
        for (String word : List.of("a", "bb", "ccc")) {
            sum += word.length() * n;
        }
        return String.valueOf(sum);
    }

    @GetMapping("/loop/while/{n}")
    public String whileLoop(@PathVariable int n) {
        int remaining = n;
        int steps = 0;
        while (remaining > 0) {
            remaining -= 2;
            steps++;
        }
        return String.valueOf(steps);
    }

    @GetMapping("/loop/do-while/{n}")
    public String doWhile(@PathVariable int n) {
        int value = n;
        int digits = 0;
        do {
            value /= 10;
            digits++;
        } while (value != 0);
        return String.valueOf(digits);
    }

    @GetMapping("/loop/nested/{n}")
    public String nested(@PathVariable int n) {
        int cells = 0;
        for (int row = 0; row < n; row++) {
            for (int col = 0; col < n; col++) {
                cells++;
            }
        }
        return String.valueOf(cells);
    }

    @GetMapping("/loop/labeled/{n}")
    public String labeled(@PathVariable int n) {
        int visited = 0;
        outer:
        for (int row = 0; row < n; row++) {
            for (int col = 0; col < n; col++) {
                if (col > row) {
                    continue outer;
                }
                if (visited > 20) {
                    break outer;
                }
                visited++;
            }
        }
        return String.valueOf(visited);
    }

    @GetMapping("/loop/self/{n}")
    public String emptyBody(@PathVariable int n) {
        // Single coarse statement looping on itself: the WHILE node's only CFG
        // successor is the WHILE node. The current projection deletes self-loops.
        AtomicInteger counter = new AtomicInteger(n);
        while (counter.decrementAndGet() > 0) { }
        return "drained";
    }

    @GetMapping("/loop/stream/{n}")
    public String streamPipeline(@PathVariable int n) {
        int total = List.of(1, 2, 3, 4)
            .stream()
            .filter(x -> x % 2 == 0)
            .mapToInt(x -> x * n)
            .sum();
        return String.valueOf(total);
    }
}
