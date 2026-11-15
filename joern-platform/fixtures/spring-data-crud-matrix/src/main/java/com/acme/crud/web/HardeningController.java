package com.acme.crud.web;

import com.acme.crud.domain.AuditedOrder;
import com.acme.crud.domain.Note;
import com.acme.crud.domain.Order;
import com.acme.crud.domain.PetLog;
import com.acme.crud.domain.Trip;
import com.acme.crud.domain.TripId;
import com.acme.crud.repo.AuditedOrderRepository;
import com.acme.crud.repo.CouponRepository;
import com.acme.crud.repo.NoteRepository;
import com.acme.crud.repo.OrderRepository;
import com.acme.crud.repo.PetLogRepository;
import com.acme.crud.repo.PetRepository;
import com.acme.crud.repo.TripRepository;
import com.acme.crud.service.MarkerTypedOrders;
import com.acme.crud.service.NoteStore;
import com.acme.crud.service.OrderBoundedStore;
import java.util.List;
import java.util.Optional;
import org.springframework.data.domain.Pageable;
import org.springframework.web.bind.annotation.DeleteMapping;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PutMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

/** Shapes the rigor review found the extraction misread or did not count
 *  (§5.2.17, "Hardening after the rigor review"): one handler per shape,
 *  named for it, served at `/crud/<shape>` like the plan's goldens. */
@RestController
@RequestMapping("/crud")
public class HardeningController {

    private final OrderRepository orderRepository;
    private final PetRepository petRepository;
    private final TripRepository tripRepository;
    private final PetLogRepository petLogRepository;
    private final NoteRepository noteRepository;
    private final AuditedOrderRepository auditedOrderRepository;
    private final CouponRepository couponRepository;
    private final MarkerTypedOrders markerTypedOrders;
    private final NoteStore noteStore;
    private final OrderBoundedStore orderBoundedStore;

    public HardeningController(
            OrderRepository orderRepository,
            PetRepository petRepository,
            TripRepository tripRepository,
            PetLogRepository petLogRepository,
            NoteRepository noteRepository,
            AuditedOrderRepository auditedOrderRepository,
            CouponRepository couponRepository,
            MarkerTypedOrders markerTypedOrders,
            NoteStore noteStore,
            OrderBoundedStore orderBoundedStore) {
        this.orderRepository = orderRepository;
        this.petRepository = petRepository;
        this.tripRepository = tripRepository;
        this.petLogRepository = petLogRepository;
        this.noteRepository = noteRepository;
        this.auditedOrderRepository = auditedOrderRepository;
        this.couponRepository = couponRepository;
        this.markerTypedOrders = markerTypedOrders;
        this.noteStore = noteStore;
        this.orderBoundedStore = orderBoundedStore;
    }

    /** Review A2: a field and a parameter declared `CrudRepository<Order, String>`. */
    @GetMapping("/marker-typed-receiver")
    public boolean markerTypedReceiver(@RequestParam String id) {
        long count = markerTypedOrders.countOrders();
        boolean exists = markerTypedOrders.exists(id);
        return count > 0 && exists;
    }

    /** Review A2: `JpaRepository<E, Long>` in a generic base; nothing binds `E`. */
    @GetMapping("/marker-receiver-unbound-entity")
    public List<Note> markerReceiverUnboundEntity() {
        return noteStore.all();
    }

    /** Review A2: a field of type `R extends JpaRepository<Order, String>`. */
    @GetMapping("/type-variable-receiver")
    public List<Order> typeVariableReceiver() {
        return orderBoundedStore.all();
    }

    /** Review A4: `KeyedJpaRepository<TripId, Trip>` binds Trip. */
    @GetMapping("/marker-named-project-base")
    public Optional<Trip> markerNamedProjectBase(@RequestParam String line, @RequestParam int day) {
        return tripRepository.findById(new TripId(line, day));
    }

    /** Review A4: `BaseCrudRepository<E> extends MongoRepository<E, String>` is mongo. */
    @GetMapping("/marker-named-mongo-base")
    public List<PetLog> markerNamedMongoBase() {
        return petLogRepository.findAll();
    }

    /** Review A3: the sub-interface's `@Query` redeclaration wins over the base. */
    @GetMapping("/redeclared-query-override")
    public List<Note> redeclaredQueryOverride(@RequestParam String text, Pageable page) {
        return noteRepository.search(text, page);
    }

    /** Review A3: two arguments against a one-parameter (varargs) declaration. */
    @GetMapping("/arity-mismatch")
    public List<Note> arityMismatch() {
        return noteRepository.findTagged("urgent", "billing");
    }

    /** Review B1: Mongo `@Update` on a finder-named method. */
    @PutMapping("/annotation-mongo-update")
    public long annotationMongoUpdate(@RequestParam String status) {
        return petRepository.findAndIncrementVisitsByStatus(status, 1);
    }

    /** Review B1: JPA `@Procedure` on a getter-named method. */
    @PutMapping("/annotation-procedure")
    public int annotationProcedure(@RequestParam String status) {
        return orderRepository.getArchivedCount(status);
    }

    /** Review B1: Mongo `@Aggregation`. */
    @GetMapping("/annotation-aggregation")
    public List<String> annotationAggregation() {
        return petRepository.findStatusSummary();
    }

    /** Review B1: `@NativeQuery` is read as a native `@Query`. */
    @GetMapping("/annotation-native-query")
    public List<Order> annotationNativeQuery(@RequestParam String status) {
        return orderRepository.findNativeAnnotated(status);
    }

    /** Review B1: `@Transactional` and `@Lock` on a derived finder. */
    @GetMapping("/annotation-neutral")
    public Order annotationNeutral(@RequestParam String status) {
        return orderRepository.findFirstByStatus(status);
    }

    /** Review B1: a project annotation meta-annotated with `@Query`. */
    @GetMapping("/annotation-project-meta-query")
    public List<Order> annotationProjectMetaQuery() {
        return orderRepository.openOrders();
    }

    /** Review B2: `audit.orders` names the entity whose `@Table` declares that schema. */
    @GetMapping("/query-native-schema-table")
    public List<AuditedOrder> queryNativeSchemaTable(@RequestParam String status) {
        return auditedOrderRepository.findAuditedByStatus(status);
    }

    /** Review B1: `deleteById` on an entity whose class carries `@SQLDelete`. */
    @DeleteMapping("/soft-delete-entity")
    public void softDeleteEntity(@RequestParam Long id) {
        couponRepository.deleteById(id);
    }
}
