package com.acme.flow;

import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.RestController;

/** Branches that carry no statements, and branches with nowhere to join.
 *
 * <p>These shapes are the ones real repositories produce and synthetic
 * fixtures miss: an arm written only to document that nothing happens
 * ({@code //do nothing}), and a construct that is the last statement of its
 * method, so the arm not taken falls straight off the end. Both were found by
 * the always-on {@code cfg_anomalies} invariants on a 22-service snapshot
 * (§5.2.8), and both are pinned here so the coarsening can never lose them
 * again. */
@RestController
public class DegenerateController {

    private int hits;

    @GetMapping("/degenerate/empty-then/{n}")
    public String emptyThenArm(@PathVariable int n) {
        String out = "unchanged";
        if (n < 0) {
            // Deliberately empty: control still flows past the if on true.
        } else {
            out = "non-negative";
        }
        return out;
    }

    @GetMapping("/degenerate/empty-else/{n}")
    public String emptyElseArm(@PathVariable int n) {
        String out = "unchanged";
        if (n < 0) {
            out = "negative";
        } else {
            // Deliberately empty: control still flows past the if on false.
        }
        return out;
    }

    /** Both arms converge on the same statement, so true and false are the
     * SAME statement-level edge — the coarse graph cannot label it twice. */
    @GetMapping("/degenerate/empty-then-no-else/{n}")
    public String emptyThenNoElse(@PathVariable int n) {
        String out = "unchanged";
        if (n < 0) {
            // Deliberately empty, and there is no else arm to flow to.
        }
        return out;
    }

    /** The if is the method's last statement: on false, control leaves the
     * method. There is no successor statement for the false arm to reach. */
    @GetMapping("/degenerate/trailing-if/{n}")
    public void trailingIf(@PathVariable int n) {
        if (n > 0) {
            hits += n;
        }
    }

    /** Same shape for a loop: the exit arm falls off the end of the method. */
    @GetMapping("/degenerate/trailing-loop/{n}")
    public void trailingLoop(@PathVariable int n) {
        for (int i = 0; i < n; i++) {
            hits++;
        }
    }

    /** A switch with no {@code default} arm, as the method's last statement:
     * when nothing matches, control leaves the method. */
    @GetMapping("/degenerate/trailing-switch/{n}")
    public void trailingSwitch(@PathVariable int n) {
        switch (n) {
            case 0:
                hits = 0;
                break;
            case 1:
                hits++;
                break;
        }
    }

    /** A try whose body is entirely commented out — nothing flows into the
     * container, so nothing flows into its handler either. */
    @GetMapping("/degenerate/empty-try/{n}")
    public String emptyTryBody(@PathVariable int n) {
        try {
            // Deliberately commented out, as in the repository this came from.
        } catch (RuntimeException e) {
            return "caught:" + n;
        }
        return "done:" + hits;
    }
}
