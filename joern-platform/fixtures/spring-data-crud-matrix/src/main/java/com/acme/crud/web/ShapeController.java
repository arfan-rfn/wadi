package com.acme.crud.web;

import com.acme.crud.billing.AccountRepository;
import com.acme.crud.domain.Issue;
import com.acme.crud.domain.Ticket;
import com.acme.crud.domain.Order;
import com.acme.crud.repo.CrmAccountRepository;
import com.acme.crud.repo.IssueRepository;
import com.acme.crud.repo.OrderRepository;
import com.acme.crud.repo.TicketRepository;
import com.acme.crud.service.IssueArchiver;
import java.util.List;
import java.util.Optional;
import org.springframework.transaction.annotation.Transactional;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.PutMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;
import org.springframework.web.client.RestTemplate;

/** Repository and entity shapes that decide WHICH entity a site names, or
 *  whether it is an entity operation at all. */
@RestController
@RequestMapping("/crud")
public class ShapeController {

    private final OrderRepository orderRepository;
    private final IssueRepository issueRepository;
    private final TicketRepository ticketRepository;
    private final AccountRepository billingAccountRepository;
    private final CrmAccountRepository crmAccountRepository;
    private final IssueArchiver issueArchiver;
    private final RestTemplate restTemplate;

    public ShapeController(
            OrderRepository orderRepository,
            IssueRepository issueRepository,
            TicketRepository ticketRepository,
            AccountRepository billingAccountRepository,
            CrmAccountRepository crmAccountRepository,
            IssueArchiver issueArchiver,
            RestTemplate restTemplate) {
        this.orderRepository = orderRepository;
        this.issueRepository = issueRepository;
        this.ticketRepository = ticketRepository;
        this.billingAccountRepository = billingAccountRepository;
        this.crmAccountRepository = crmAccountRepository;
        this.issueArchiver = issueArchiver;
        this.restTemplate = restTemplate;
    }

    /** Golden 14: an inherited method and a base-declared method, both on a
     *  repository that reaches its marker only through a project interface,
     *  and a base whose parameters are in the opposite order to the marker's. */
    @PostMapping("/base-interface-repository")
    public List<Issue> baseInterfaceRepository(@RequestBody List<Long> ids) {
        Optional<Issue> first = issueRepository.findById(ids.get(0));
        List<Issue> rest = issueRepository.findAllByIdIn(ids);
        Optional<Ticket> ticket = ticketRepository.findById("t-1");
        return first.isPresent() && ticket.isPresent() ? rest : List.of();
    }

    /** Golden 27: the update happens by dirty checking; the only site is the read. */
    @Transactional
    @PutMapping("/dirty-checking-setter")
    public void dirtyCheckingSetter(@RequestParam String id, @RequestParam String status) {
        Order order = orderRepository.findById(id).orElseThrow();
        order.setStatus(status);
    }

    /** Golden 28: forwards to another service and touches no repository. */
    @PutMapping("/forwarding-endpoint")
    public String forwardingEndpoint(@RequestParam String id) {
        return restTemplate.getForObject("http://ts-station-service:12345/api/v1/stations/" + id, String.class);
    }

    /** Golden 30: the receiver is the generic base interface; nothing binds `E`. */
    @GetMapping("/unbindable-entity-chain")
    public long unbindableEntityChain() {
        return issueArchiver.countAll();
    }

    /** Golden 32: a `default` repository method named like a finder that writes. */
    @PutMapping("/repository-default-method")
    public Order repositoryDefaultMethod(@RequestParam String id) {
        return orderRepository.findAndTouch(id);
    }

    /** Golden 33: a custom fragment method with a body in the project. */
    @PostMapping("/repository-custom-fragment")
    public int repositoryCustomFragment() {
        return orderRepository.archiveOld();
    }

    /** Golden 36: two entities share the simple name `Account`. */
    @GetMapping("/same-simple-name-two-packages")
    public boolean sameSimpleNameTwoPackages(@RequestParam Long id) {
        boolean billing = billingAccountRepository.findById(id).isPresent();
        boolean crm = crmAccountRepository.findById(id).isPresent();
        return billing && crm;
    }
}
