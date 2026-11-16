package com.acme.crud.web;

import com.acme.crud.domain.Order;
import com.acme.crud.repo.OrderRepository;
import com.acme.crud.service.OrderEnvelope;
import com.acme.crud.service.OrderLookup;
import com.acme.crud.service.OrderWriter;
import java.util.List;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.PutMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

/** Save shapes: where the saved object came from decides the candidate
 *  operation (rule 3). Each pins its `save` raw facts (Phase 2.10 M1b). */
@RestController
@RequestMapping("/crud")
public class SaveController {

    private final OrderRepository orderRepository;
    private final OrderWriter orderWriter;
    private final OrderLookup orderLookup;

    public SaveController(OrderRepository orderRepository, OrderWriter orderWriter, OrderLookup orderLookup) {
        this.orderRepository = orderRepository;
        this.orderWriter = orderWriter;
        this.orderLookup = orderLookup;
    }

    /** Golden 2: the saved object was read in the same method. */
    @PutMapping("/inherited-save-read-origin")
    public Order inheritedSaveReadOrigin(@RequestParam String id, @RequestParam String status) {
        Order order = orderRepository.findById(id).orElseThrow();
        order.setStatus(status);
        return orderRepository.save(order);
    }

    /** Golden 15. */
    @PostMapping("/save-constructed-no-lookup")
    public Order saveConstructedNoLookup(@RequestParam String status) {
        Order order = new Order();
        order.setStatus(status);
        return orderRepository.save(order);
    }

    /** Golden 16: constructed inside the not-found arm. */
    @PostMapping("/save-guard-not-found-arm")
    public Order saveGuardNotFoundArm(@RequestParam String id) {
        if (!orderRepository.existsById(id)) {
            Order order = new Order(id);
            order.setStatus("NEW");
            return orderRepository.save(order);
        }
        return null;
    }

    /** Golden 17: constructed inside the found arm. */
    @PutMapping("/save-guard-found-arm")
    public Order saveGuardFoundArm(@RequestParam String id, @RequestParam String status) {
        if (orderRepository.existsById(id)) {
            Order order = new Order(id);
            order.setStatus(status);
            return orderRepository.save(order);
        }
        throw new IllegalArgumentException("no order " + id);
    }

    /** Golden 18: the existence check returns early; the save is in no arm. */
    @PostMapping("/save-guard-early-return")
    public Order saveGuardEarlyReturn(@RequestParam String id) {
        if (orderRepository.existsById(id)) {
            return null;
        }
        Order order = new Order(id);
        return orderRepository.save(order);
    }

    /** Golden 19: a read on one branch, a new object on the other. */
    @PutMapping("/save-upsert-by-branch")
    public Order saveUpsertByBranch(@RequestParam String id, @RequestParam boolean fresh) {
        Order order;
        if (fresh) {
            order = new Order(id);
        } else {
            order = orderRepository.findById(id).orElseThrow();
        }
        order.setStatus("UPSERTED");
        return orderRepository.save(order);
    }

    /** Golden 20: both callers of the saving method pass a read object. */
    @PutMapping("/save-parameter-callers-agree")
    public void saveParameterCallersAgree(@RequestParam String first, @RequestParam String second) {
        Order a = orderRepository.findById(first).orElseThrow();
        Order b = orderRepository.findById(second).orElseThrow();
        orderWriter.storeAgreed(a);
        orderWriter.storeAgreed(b);
    }

    /** Golden 21: one caller passes a read object, the other a new one. */
    @PutMapping("/save-parameter-callers-disagree")
    public void saveParameterCallersDisagree(@RequestParam String id) {
        Order loaded = orderRepository.findById(id).orElseThrow();
        orderWriter.storeDisagreed(loaded);
        orderWriter.storeDisagreed(new Order(id + "-copy"));
    }

    /** Golden 22: the caller passes its own request body. */
    @PostMapping("/save-parameter-from-request-body")
    public Order saveParameterFromRequestBody(@RequestBody Order order) {
        return orderWriter.storeBody(order);
    }

    /** Golden 23: the read arrives through a helper returning a wrapper. */
    @PutMapping("/save-via-helper-wrapper")
    public Order saveViaHelperWrapper(@RequestParam String id) {
        OrderEnvelope envelope = orderLookup.loadEnvelope(id);
        Order order = envelope.getOrder();
        order.setStatus("WRAPPED");
        return orderRepository.save(order);
    }

    /** Golden 24: delete, then save of a rebuilt object (a static factory). */
    @PutMapping("/delete-then-save")
    public Order deleteThenSave(@RequestParam String id) {
        orderRepository.deleteById(id);
        Order rebuilt = Order.withId(id);
        rebuilt.setStatus("REBUILT");
        return orderRepository.save(rebuilt);
    }

    /** Golden 25: two repository calls in one statement, two sites (R1-2). */
    @PutMapping("/two-calls-one-statement")
    public Order twoCallsOneStatement(@RequestParam String id) {
        return orderRepository.save(orderRepository.findById(id).orElseThrow());
    }

    /** Golden 26: the save sits in a lambda body, in the export but in no
     *  endpoint flow (R1-1). */
    @PostMapping("/save-in-lambda")
    public void saveInLambda(@RequestBody List<String> ids) {
        ids.forEach(id -> orderRepository.save(new Order(id)));
    }
}
