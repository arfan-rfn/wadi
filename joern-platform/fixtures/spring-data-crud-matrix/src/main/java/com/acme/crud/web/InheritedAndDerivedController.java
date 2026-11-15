package com.acme.crud.web;

import com.acme.crud.domain.AuditEntry;
import com.acme.crud.domain.Order;
import com.acme.crud.domain.Pet;
import com.acme.crud.repo.AuditEntryRepository;
import com.acme.crud.repo.OrderRepository;
import com.acme.crud.repo.PetRepository;
import java.util.List;
import java.util.Optional;
import org.springframework.web.bind.annotation.DeleteMapping;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

/** Goldens whose verb is read from a Spring Data method name: inherited
 *  CRUD methods and derived queries. */
@RestController
@RequestMapping("/crud")
public class InheritedAndDerivedController {

    private final OrderRepository orderRepository;
    private final PetRepository petRepository;
    private final AuditEntryRepository auditEntryRepository;

    public InheritedAndDerivedController(
            OrderRepository orderRepository,
            PetRepository petRepository,
            AuditEntryRepository auditEntryRepository) {
        this.orderRepository = orderRepository;
        this.petRepository = petRepository;
        this.auditEntryRepository = auditEntryRepository;
    }

    /** Golden 1. */
    @GetMapping("/inherited-find-by-id")
    public Optional<Order> inheritedFindById(@RequestParam String id) {
        return orderRepository.findById(id);
    }

    /** Golden 3. */
    @DeleteMapping("/inherited-delete")
    public void inheritedDelete(@RequestParam String id) {
        orderRepository.deleteById(id);
    }

    /** Golden 4. */
    @GetMapping("/derived-find-by-status")
    public List<Order> derivedFindByStatus(@RequestParam String status) {
        return orderRepository.findByStatus(status);
    }

    /** Golden 5. */
    @DeleteMapping("/derived-delete-by")
    public long derivedDeleteBy(@RequestParam String status) {
        return orderRepository.deleteByStatus(status);
    }

    /** Golden 6: two derived reads, two sites. */
    @GetMapping("/derived-count-exists")
    public boolean derivedCountExists(@RequestParam String status) {
        long count = orderRepository.countByStatus(status);
        boolean exists = orderRepository.existsByStatus(status);
        return exists && count > 0;
    }

    /** Golden 34: the inherited CrudRepository / JpaRepository / MongoRepository
     *  methods the verb table must name (E5), one statement each. */
    @PostMapping("/inherited-method-table")
    public long inheritedMethodTable(@RequestBody List<String> ids) {
        List<Order> all = orderRepository.findAll();
        List<Order> some = orderRepository.findAllById(ids);
        long total = orderRepository.count();
        boolean present = orderRepository.existsById("o-1");
        Order reference = orderRepository.getReferenceById("o-1");
        orderRepository.saveAll(some);
        orderRepository.saveAndFlush(reference);
        orderRepository.saveAllAndFlush(all);
        orderRepository.deleteAllById(ids);
        orderRepository.deleteAllInBatch();
        orderRepository.deleteAll();
        petRepository.insert(new Pet("NEW"));
        return present ? total : 0;
    }

    /** Golden 35: flush is not an entity operation. */
    @PostMapping("/flush-not-an-operation")
    public void flushNotAnOperation() {
        orderRepository.flush();
    }

    /** Golden 29: the entity is named only by its repository. */
    @GetMapping("/repository-only-entity")
    public Iterable<AuditEntry> repositoryOnlyEntity() {
        return auditEntryRepository.findAll();
    }
}
