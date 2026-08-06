package com.acme.shapes;

import java.util.List;

import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

import static org.springframework.http.ResponseEntity.ok;

/**
 * The regression guard. These signatures declare their payload, so recovery
 * must never run and `origin` must stay `declared` — a fallback that fired
 * here would mean one return path had quietly replaced a stated contract.
 */
@RestController
@RequestMapping("/declared")
public class DeclaredController {

    private final ItemService service = new ItemService();

    private final EnvelopeService envelopes = new EnvelopeService();

    @GetMapping("/list")
    public ResponseEntity<List<Item>> list() {
        return ok(service.findAll());
    }

    @GetMapping("/one")
    public ResponseEntity<Item> one() {
        return ok(service.findOne());
    }

    /**
     * A DECLARED generic wrapping a RAW envelope — the shape that escaped T8.
     *
     * `ResponseEntity<Envelope>` has a type argument, so it never took the
     * recovery path, while the `Envelope` inside it is as raw as any recovered
     * one. Binding only on recovery left this reading `data: T` while a handler
     * one line different resolved fully.
     */
    @GetMapping("/wrapped-envelope")
    public ResponseEntity<Envelope> wrappedEnvelope() {
        return ok(envelopes.findAll());
    }

    /** A declared argument answers outright: `Envelope<Item>` says T=Item. */
    @GetMapping("/declared-argument")
    public ResponseEntity<Envelope<Item>> declaredArgument() {
        return ok(null);
    }

    /** Names no status at all: the framework answers 200, the code does not. */
    @GetMapping("/welcome")
    public String welcome() {
        return "Welcome";
    }
}
