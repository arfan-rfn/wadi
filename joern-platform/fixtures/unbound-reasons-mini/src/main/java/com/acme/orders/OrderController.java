package com.acme.orders;

import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.RestController;
import org.springframework.web.client.RestTemplate;

import static org.springframework.http.ResponseEntity.ok;

/**
 * One endpoint whose body exercises every unbound-callee reason (§5.4.2 T5).
 * Each of these calls IS a real call with real runtime effect, so the CFG must
 * keep the node; what it cannot do is open it, and the reason code is how the
 * map says so instead of looking like a hole (P10).
 */
@RestController
public class OrderController {

    private final OrderRepository repository = null;

    private final RestTemplate restTemplate = new RestTemplate();

    private final OrderSummary summary = new OrderSummary();

    private final OrderFormatter formatter = new OrderFormatter();

    @GetMapping("/orders/{id}")
    public ResponseEntity<String> lookup(@PathVariable String id) {
        Order order = new Order();
        // lombok-generated: setter/getter synthesized by @Data.
        order.setId(id);
        String found = order.getId();

        // inherited-external: declared by CrudRepository, not by OrderRepository.
        repository.save(order);

        // compiler-generated: javac synthesizes values() on every enum.
        OrderStatus[] all = OrderStatus.values();

        // third-party: the declaring type is not in this CPG at all.
        String upstream = restTemplate.getForObject("http://upstream:9000/x", String.class);

        // resolves normally — a first-party method with a real body, proving
        // the classifier does not label calls that bind fine.
        String label = summary.describe(found, all.length);

        // NOT an accessor despite the "set" prefix, and hand-written: must
        // never be reported lombok-generated.
        String settled = formatter.settle(id);

        // The setter comes from a FIELD-level @Setter on a class annotated
        // @Getter — still Lombok-generated, still no source to open.
        formatter.setPrefix(settled);

        // Two first-party overloads of `format`; whichever way the receiver
        // binds, the classifier must not invent a body.
        String formatted = formatter.format(id, all.length);

        // A Lombok-generated constructor: no declaration exists for THIS
        // overload, only a bodiless no-arg stub the classifier must not
        // mistake for source (§5.2.11 T7).
        Envelope envelope = new Envelope(1, label, formatted);

        // unresolved-receiver: `ok` is a static import of
        // ResponseEntity.ok, which javasrc2cpg attributes to THIS class.
        return ok(label + upstream + formatted + envelope.getMsg());
    }
}
