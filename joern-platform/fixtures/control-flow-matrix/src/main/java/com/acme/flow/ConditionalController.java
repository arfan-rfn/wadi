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

    /** Allocation inside the SHORT-CIRCUITED operand, with an else.
     *
     * javasrc2cpg lowers `new int[]{n}` into a block holding `$obj = new …`,
     * whose children sit in statement position — a node in NEITHER arm on the
     * branch's successor list. Before 2026-08-05 this surfaced as an
     * `unlabeled-arm` anomaly. A plain method call in the operand does NOT do
     * it (see `shortCircuit` above, which is why the matrix missed the shape
     * for two releases: a fixture author writes cheap conditions). */
    @GetMapping("/cond/alloc-in-condition/{n}")
    public String allocInCondition(@PathVariable int n) {
        if (n > 0 && new int[] { n }.length > 0) {
            return "allocated-and-positive";
        } else {
            return "not-positive";
        }
    }

    /** The same allocation with NO else — the silently-wrong half.
     *
     * With both arms non-empty the mislabelled edge stayed `flow` and was
     * reported. Here `falseEmpty` is true, so before the fix the empty-arm
     * heuristic stamped the condition-lowering edge `false`: the graph grew a
     * SECOND `false` successor that does not exist, and the invariants
     * reported clean. This is the common shape — a guard clause. */
    @GetMapping("/cond/alloc-in-condition-no-else/{n}")
    public String allocInConditionNoElse(@PathVariable int n) {
        if (n > 0 && new int[] { n }.length > 0) {
            return "guarded";
        }
        return "fell-through";
    }

    /** `||` reaches the same lowering by the other operator. */
    @GetMapping("/cond/alloc-in-or-condition/{n}")
    public String allocInOrCondition(@PathVariable int n) {
        if (n < 0 || new int[] { n }.length > 0) {
            return "matched";
        } else {
            return "unmatched";
        }
    }
}
