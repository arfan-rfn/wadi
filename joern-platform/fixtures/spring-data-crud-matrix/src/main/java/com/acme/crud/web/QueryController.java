package com.acme.crud.web;

import com.acme.crud.domain.Customer;
import com.acme.crud.domain.Issue;
import com.acme.crud.domain.Order;
import com.acme.crud.domain.OrderLine;
import com.acme.crud.domain.Pet;
import com.acme.crud.repo.CustomerRepository;
import com.acme.crud.repo.InvoiceRepository;
import com.acme.crud.repo.IssueRepository;
import com.acme.crud.repo.OrderLineRepository;
import com.acme.crud.repo.OrderRepository;
import com.acme.crud.repo.PetRepository;
import java.math.BigDecimal;
import java.util.List;
import org.springframework.web.bind.annotation.DeleteMapping;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PutMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

/** Goldens whose method carries a query: the name never decides the verb
 *  (R1-12). */
@RestController
@RequestMapping("/crud")
public class QueryController {

    private final OrderRepository orderRepository;
    private final OrderLineRepository orderLineRepository;
    private final CustomerRepository customerRepository;
    private final InvoiceRepository invoiceRepository;
    private final PetRepository petRepository;
    private final IssueRepository issueRepository;

    public QueryController(
            OrderRepository orderRepository,
            OrderLineRepository orderLineRepository,
            CustomerRepository customerRepository,
            InvoiceRepository invoiceRepository,
            PetRepository petRepository,
            IssueRepository issueRepository) {
        this.orderRepository = orderRepository;
        this.orderLineRepository = orderLineRepository;
        this.customerRepository = customerRepository;
        this.invoiceRepository = invoiceRepository;
        this.petRepository = petRepository;
        this.issueRepository = issueRepository;
    }

    /** Golden 7. */
    @GetMapping("/query-jpql-select")
    public List<OrderLine> queryJpqlSelect(@RequestParam String sku) {
        return orderLineRepository.findBySkuText(sku);
    }

    /** Golden 8. */
    @PutMapping("/query-jpql-update-modifying")
    public int queryJpqlUpdateModifying(@RequestParam String id, @RequestParam String status) {
        return orderRepository.updateStatus(id, status);
    }

    /** Golden 9. */
    @GetMapping("/query-jpql-join-association")
    public List<Order> queryJpqlJoinAssociation(@RequestParam String sku) {
        return orderRepository.findContainingSku(sku);
    }

    /** Golden 10. */
    @GetMapping("/query-jpql-keyword-entity")
    public List<Order> queryJpqlKeywordEntity(@RequestParam String status) {
        return orderRepository.findInStatus(status);
    }

    /** Golden 11. */
    @GetMapping("/query-native-table")
    public List<Order> queryNativeTable(@RequestParam String status) {
        List<Order> plain = orderRepository.findNativeByStatus(status);
        List<Order> concatenated = orderRepository.findNativeConcatenated(status, "o-1");
        return plain.isEmpty() ? concatenated : plain;
    }

    /** Golden 12: an explicit `@Query(name=)` resolved through `@NamedQuery`,
     *  one resolved through a `@NamedQueries` container on a base-interface
     *  repository (ICPC), an implicit named query keyed by the JPQL name, an
     *  implicit named native query, and a name nothing declares. */
    @GetMapping("/query-named")
    public BigDecimal queryNamed() {
        List<Order> shipped = orderRepository.shipped();
        List<Issue> open = issueRepository.findOpen();
        List<Customer> vips = customerRepository.findVip();
        BigDecimal unpaid = invoiceRepository.sumOpen();
        List<Order> undeclared = orderRepository.undeclaredNamed();
        return shipped.isEmpty() && open.isEmpty() && vips.isEmpty() && undeclared.isEmpty()
                ? BigDecimal.ZERO
                : unpaid;
    }

    /** Golden 13. */
    @GetMapping("/query-mongo-json")
    public List<Pet> queryMongoJson(@RequestParam String status) {
        return petRepository.findByStatusJson(status);
    }

    /** Golden 31: one site, two accesses. */
    @DeleteMapping("/query-delete-with-subquery")
    public int queryDeleteWithSubquery() {
        return invoiceRepository.deleteForNonVip();
    }
}
