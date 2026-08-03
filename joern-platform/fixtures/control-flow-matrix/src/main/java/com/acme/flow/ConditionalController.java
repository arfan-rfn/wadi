package com.acme.flow;

import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.RestController;
import org.springframework.web.client.RestTemplate;

/** One handler per conditional construct. Every endpoint is deterministic and
 * both branch outcomes are reachable by choosing {n}, so the M4 dynamic layer
 * can execute each side. */
@RestController
public class ConditionalController {

    private final RestTemplate rest = new RestTemplate();

    @GetMapping("/cond/if/{n}")
    public String plainIf(@PathVariable int n) {
        String out = "non-negative";
        if (n < 0) {
            out = "negative";
        }
        return out;
    }

    @GetMapping("/cond/if-else/{n}")
    public String ifElse(@PathVariable int n) {
        if (n % 2 == 0) {
            return "even";
        } else {
            return "odd";
        }
    }

    @GetMapping("/cond/else-if/{n}")
    public String elseIfChain(@PathVariable int n) {
        if (n < 0) {
            return "negative";
        } else if (n == 0) {
            return "zero";
        } else if (n < 10) {
            return "small";
        } else {
            return "large";
        }
    }

    @GetMapping("/cond/ternary/{n}")
    public String ternary(@PathVariable int n) {
        return n < 0 ? "negative" : "non-negative";
    }

    @GetMapping("/cond/short-circuit/{n}")
    public String shortCircuit(@PathVariable int n) {
        if (n > 0 && n % 3 == 0) {
            return "positive-multiple-of-3";
        }
        if (n < 0 || n > 100) {
            return "out-of-range";
        }
        return "in-range";
    }

    @GetMapping("/cond/sink-in-condition/{n}")
    public String sinkInCondition(@PathVariable int n) {
        // Probe: an http-client sink whose call site IS the branch condition.
        // Wrapped so the endpoint still answers when no upstream exists (M4).
        try {
            if (rest.getForObject("http://inventory:8080/ping", String.class) != null) {
                return "upstream-alive";
            }
            return "upstream-silent";
        } catch (RuntimeException e) {
            return "upstream-unreachable";
        }
    }
}
