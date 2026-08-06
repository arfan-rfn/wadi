package com.acme.shapes;

import java.util.concurrent.atomic.AtomicInteger;

import org.springframework.http.HttpEntity;
import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.ResponseStatus;
import org.springframework.web.bind.annotation.RestController;

import static org.springframework.http.ResponseEntity.ok;

/**
 * Raw-wrapper handlers: the dominant TrainTicket idiom (376 raw `HttpEntity`
 * declarations against 9 generic ones), where the signature names no payload
 * and the return expression does.
 *
 * The class-level mapping deliberately OMITS its leading slash. Spring routes
 * `shapes` exactly as `/shapes`, and two real controllers in the corpus are
 * written this way — every URI below must still be published root-anchored
 * (§5.2.11 / T0).
 */
@RestController
@RequestMapping("shapes")
public class ShapeController {

    private final ItemService service = new ItemService();

    private final EnvelopeService envelopes = new EnvelopeService();

    /** Recovery: `ok(expr)` where the callee declares the payload. */
    @GetMapping("/one")
    public HttpEntity one() {
        return ok(service.findOne());
    }

    /** Recovery through generics — the callee declares `List<Item>`. */
    @GetMapping("/list")
    public HttpEntity list() {
        return ok(service.findAll());
    }

    /** Recovery: the constructor form, payload at argument 1. */
    @PostMapping("/created")
    public HttpEntity created() {
        return new ResponseEntity<>(service.findOne(), HttpStatus.CREATED);
    }

    /**
     * The envelope case: the payload type lives in the producer's return
     * statement and nowhere else (§5.2.7 T8). Recovering only `{status, msg,
     * data: T}` named the wrapper and withheld the one field a reader wants —
     * which is what 291 of 365 train-ticket-aitest endpoints published.
     */
    @GetMapping("/envelope")
    public HttpEntity envelope() {
        return ok(envelopes.findAll());
    }

    /** Every path sends null: `data` is empty, and says so. */
    @GetMapping("/envelope-empty")
    public HttpEntity envelopeEmpty() {
        return ok(envelopes.acknowledgeOnly(true));
    }

    /** Two constructions that disagree about T: it must stay unresolved. */
    @GetMapping("/envelope-conflict")
    public HttpEntity envelopeConflict() {
        return ok(envelopes.conflicting(true));
    }

    /** The builder's NAME fixes the status: 204, no body anywhere. */
    @GetMapping("/status-builder")
    public HttpEntity statusBuilder() {
        return ResponseEntity.noContent().build();
    }

    /** An explicit constant beats any builder default. */
    @PostMapping("/status-explicit")
    public HttpEntity statusExplicit() {
        return new ResponseEntity<>(service.findOne(), HttpStatus.CREATED);
    }

    /** `status(X).body(y)` — the chain fixes X, the body is not the status. */
    @PostMapping("/status-chain")
    public HttpEntity statusChain() {
        return ResponseEntity.status(HttpStatus.ACCEPTED).body(service.findOne());
    }

    /** Two paths, two statuses: both are declared, neither wins. */
    @GetMapping("/status-branching")
    public HttpEntity statusBranching(@RequestParam boolean flag) {
        if (flag) {
            return ResponseEntity.notFound().build();
        }
        return ok(service.findOne());
    }

    /**
     * `@ResponseStatus` REPLACES what the builder would imply — the framework
     * sends 202 here, so publishing the `ok(...)` 200 beside it would name a
     * status this endpoint never answers with.
     */
    @ResponseStatus(HttpStatus.ACCEPTED)
    @GetMapping("/status-annotated")
    public HttpEntity statusAnnotated() {
        return ok(service.findOne());
    }

    /**
     * Honest unknown: two returns, two types. Neither is "the" response shape
     * and recovery must not elect a winner — this stays unresolved, and its
     * origin stays `declared`, proving no inference was published (P10).
     */
    @GetMapping("/disagree")
    public HttpEntity disagree(@RequestParam boolean flag) {
        if (flag) {
            return ok(service.findOne());
        }
        return ok(service.describe());
    }

    /** Honest unknown: a builder chain carrying no body at all. */
    @GetMapping("/empty")
    public HttpEntity empty() {
        return ResponseEntity.noContent().build();
    }

    /** Honest unknown: the payload's type is not in this CPG. */
    @GetMapping("/offcpg")
    public HttpEntity offCpg() {
        return ok(new AtomicInteger(1));
    }
}
