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
     * container, so nothing flows into its handler either.
     *
     * <p>Note the try is the method's FIRST statement, which is the one shape
     * where a missing incoming edge is invisible. {@link #emptyTryAfterWork}
     * covers the case with a predecessor. */
    @GetMapping("/degenerate/empty-try/{n}")
    public String emptyTryBody(@PathVariable int n) {
        try {
            // Deliberately commented out, as in the repository this came from.
        } catch (RuntimeException e) {
            return "caught:" + n;
        }
        return "done:" + hits;
    }

    /** An empty try with a statement BEFORE it. Routing the container has to
     * reroute that predecessor through the try; leaving it wired straight to
     * the statement after would give the method two entry points and give the
     * following statement two independent predecessors. */
    @GetMapping("/degenerate/empty-try-after-work/{n}")
    public String emptyTryAfterWork(@PathVariable int n) {
        hits += n;
        try {
            // Deliberately commented out.
        } catch (RuntimeException e) {
            return "caught:" + n;
        }
        return "done:" + hits;
    }

    /** An empty try nested inside an if-arm, so it has no next SIBLING — the
     * statement it completes into is the one after the enclosing if. Reading
     * only the immediate parent block finds nothing here, and a construct
     * whose every successor is a handler is otherwise taken to have left the
     * method: the graph would claim this returns on normal completion. */
    @GetMapping("/degenerate/empty-try-nested/{n}")
    public String emptyTryNested(@PathVariable int n) {
        if (n > 0) {
            try {
                // Deliberately commented out.
            } catch (RuntimeException e) {
                hits = -1;
            }
        }
        return "done:" + hits;
    }

    /** An empty try with a {@code finally}: normal completion goes into the
     * finally, not to the statement after the construct. */
    @GetMapping("/degenerate/empty-try-finally/{n}")
    public String emptyTryFinally(@PathVariable int n) {
        try {
            // Deliberately commented out.
        } finally {
            hits += n;
        }
        return "done:" + hits;
    }

    /** try-with-resources: the resource declaration is a child of the TRY
     * alongside the body, so "the body block" is not simply "the first block
     * child". Pinned because picking the wrong one makes a NON-empty try look
     * empty, which routes the handler as normal flow. */
    @GetMapping("/degenerate/try-with-resources/{n}")
    public String tryWithResources(@PathVariable int n) {
        try (AutoCloseable c = () -> hits++) {
            hits += n;
        } catch (Exception e) {
            return "caught:" + n;
        }
        return "done:" + hits;
    }

    /** An intentionally infinite loop. Its label set is indistinguishable from
     * a trailing loop's — body arm plus a back edge, no exit arm — but there
     * is no exit path to name: synthesizing one would assert the method can
     * return, and this method cannot. */
    @GetMapping("/degenerate/infinite-loop/{n}")
    public void infiniteLoop(@PathVariable int n) {
        while (true) {
            hits += n;
        }
    }

    /** The other infinite form: a {@code for} with no condition clause at all,
     * so there is no condition text to read. */
    @GetMapping("/degenerate/infinite-for/{n}")
    public void infiniteFor(@PathVariable int n) {
        for (;;) {
            hits += n;
        }
    }

    /** An arrow switch in EXPRESSION position, with STATEMENT-bodied arms.
     *
     * `yieldForm` above pins the block-bodied default; this pins two ordinary
     * case arms. javasrc2cpg emits arm→carrier — the arm's VALUE flowing into
     * the assignment — and no carrier→arm, so before 2026-08-05 every arm had
     * no incoming edge and read as unreachable. Statement position was always
     * correct; this is the same shape given the same wiring. */
    @GetMapping("/degenerate/expression-switch/{n}")
    public String expressionSwitchArms(@PathVariable int n) {
        String label = switch (n) {
            case 0 -> low(n);
            case 1 -> high(n);
            default -> other(n);
        };
        return label;
    }

    /** An anonymous class opening a try body.
     *
     * `Runnable r = new Runnable() { ... };` puts the allocation call and the
     * declaration on ONE line. The container's entry was picked by (line, id),
     * the tie fell to node id, and javasrc2cpg numbered the call lower — so the
     * container was wired to the call while the enclosing arm still pointed at
     * the declaration. The reroute matched nothing and the TRY was left with no
     * incoming edge at all. */
    @GetMapping("/degenerate/anon-in-try/{n}")
    public String anonymousOpensTry(@PathVariable int n) {
        if (n > 0) {
            try {
                Runnable r = new Runnable() {
                    @Override
                    public void run() {
                        marker = 1;
                    }
                };
                r.run();
            } finally {
                marker = 0;
            }
            return "ran";
        }
        return "skipped";
    }

    private int marker;

    private String low(int n) {
        return "low" + n;
    }

    private String high(int n) {
        return "high" + n;
    }

    private String other(int n) {
        return "other" + n;
    }

    /** A catch that SWALLOWS — an empty handler body.
     *
     * No interior means the container router finds no entry and wires neither
     * side, so the CATCH projected fully isolated: an unreachable handler,
     * which on the map reads as "this error path cannot happen". */
    @GetMapping("/degenerate/empty-catch/{n}")
    public String emptyCatchBody(@PathVariable int n) {
        try {
            marker = 10 / n;
        } catch (ArithmeticException e) {
        }
        return "swallowed";
    }

    /** A try whose body's TAIL leaves the method.
     *
     * javasrc2cpg's try-tail→handler approximation has no normal tail to start
     * from — even though that very throw is what the handler catches — so the
     * CATCH had no incoming edge. */
    @GetMapping("/degenerate/throwing-try/{n}")
    public String tryBodyEndsInThrow(@PathVariable int n) {
        try {
            if (n > 0) {
                return "positive";
            }
            throw new IllegalArgumentException("non-positive");
        } catch (IllegalArgumentException e) {
            return "rejected";
        }
    }
}
