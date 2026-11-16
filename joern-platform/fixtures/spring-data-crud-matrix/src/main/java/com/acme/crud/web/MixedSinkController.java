package com.acme.crud.web;

import com.acme.crud.domain.Order;
import com.acme.crud.repo.OrderRepository;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;
import org.springframework.web.client.RestTemplate;

/** One statement that makes a repository call and an HTTP call, nested each
 *  way (§5.2.17, "Found by the pre-landing review"): every sink call the
 *  statement owns gets its own row, whichever of them is the primary call. */
@RestController
@RequestMapping("/crud")
public class MixedSinkController {

    private final OrderRepository orderRepository;
    private final RestTemplate restTemplate;

    public MixedSinkController(OrderRepository orderRepository, RestTemplate restTemplate) {
        this.orderRepository = orderRepository;
        this.restTemplate = restTemplate;
    }

    /** Golden 52: the HTTP call is the primary call; the read is its argument. */
    @PostMapping("/http-wraps-repository")
    public String httpWrapsRepository(@RequestParam String id) {
        return restTemplate.postForObject("http://ts-order-service:12346/api/v1/orders", orderRepository.findById(id).get(), String.class);
    }

    /** Golden 53: the save is the primary call; it saves what the HTTP call returned. */
    @PostMapping("/repository-wraps-http")
    public Order repositoryWrapsHttp(@RequestParam String id) {
        return orderRepository.save(restTemplate.getForObject("http://ts-order-service:12346/api/v1/orders/" + id, Order.class));
    }
}
