package com.acme.petstore;

import com.acme.common.StockQuery;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.http.HttpMethod;
import org.springframework.stereotype.Service;
import org.springframework.web.client.RestTemplate;
import org.springframework.web.reactive.function.client.WebClient;

@Service
public class PetServiceImpl implements PetService {

    private static final String PRIMARY_URL = "http://inventory:8081";
    private static final String AUDIT_URL = "https://audit.example.com";

    @Value("${inventory.url}")
    private String inventoryUrl;

    private final RestTemplate restTemplate;
    private final WebClient webClient;
    private final InventoryClient inventoryClient;
    private final EndpointRegistry endpointRegistry;
    private final ServiceUrlResolver serviceUrlResolver;
    private final BillingNotifier billingNotifier;
    private final LegacyBillingBridge legacyBillingBridge;
    private final StatsService statsService;
    private final boolean preferAudit;

    public PetServiceImpl(
            RestTemplate restTemplate,
            WebClient webClient,
            InventoryClient inventoryClient,
            EndpointRegistry endpointRegistry,
            ServiceUrlResolver serviceUrlResolver,
            BillingNotifier billingNotifier,
            LegacyBillingBridge legacyBillingBridge,
            StatsService statsService,
            boolean preferAudit) {
        this.restTemplate = restTemplate;
        this.webClient = webClient;
        this.inventoryClient = inventoryClient;
        this.endpointRegistry = endpointRegistry;
        this.serviceUrlResolver = serviceUrlResolver;
        this.billingNotifier = billingNotifier;
        this.legacyBillingBridge = legacyBillingBridge;
        this.statsService = statsService;
        this.preferAudit = preferAudit;
    }

    @Override
    public String findPet(String id) {
        // Config-key slice: ${inventory.url}/stock/{?} at HIGH confidence.
        Integer stock = restTemplate.getForObject(inventoryUrl + "/stock/" + id, Integer.class);
        // Feign path: same target service resolved by discovery name (M5).
        Integer viaFeign = inventoryClient.getStock(id);
        // Service-registry idiom (TrainTicket): DI interface -> constant map ->
        // interprocedural return resolution.
        Integer viaResolver = restTemplate.getForObject(
                serviceUrlResolver.getServiceUrl("inventory-api") + "/stock/" + id, Integer.class);
        return "pet-" + id + ":" + stock + "/" + viaFeign + "/" + viaResolver;
    }

    @Override
    public String listPets(String owner) {
        // Multi-path slice: two assignments -> one candidate per branch (§5.2).
        String base = PRIMARY_URL;
        if (preferAudit) {
            base = AUDIT_URL;
        }
        restTemplate.postForObject(base + "/events", owner, String.class);

        // DB-row trap: the target only exists at runtime -> honest NONE (P10).
        String callbackUrl = endpointRegistry.lookupCallbackUrl(owner);
        restTemplate.postForObject(callbackUrl, owner, String.class);

        // Owner-scoped member + suspected-sink fixture paths (§5.2.5).
        billingNotifier.report(owner);
        legacyBillingBridge.charge(owner);
        // Interface -> abstract base -> impl chain (§5.2.6).
        statsService.weekly(owner);
        return "pets-of-" + owner;
    }

    @Override
    public String reserveStock(String id, String count) {
        // TrainTicket long-concat + exchange (§5.2.5): the slice must survive a
        // five-operand URL (depth measures indirection, not expression size)
        // and the verb comes from the HttpMethod argument, not the method name.
        return restTemplate.exchange(
                serviceUrlResolver.getServiceUrl("inventory-api") + "/stock/reserve/" + id + "/" + count,
                HttpMethod.PUT, null, String.class).getBody();
    }

    @Override
    public String stockAlert(String id) {
        // WebClient fluent chain (§5.2.5): the .uri(...) step carries the URL;
        // the chain root carries the verb.
        return webClient.post().uri("http://inventory:8081/admin/restock")
                .retrieve().bodyToMono(String.class).block();
    }

    @Override
    public String stockSummary(StockQuery query) {
        // Shared-module DTO in the DI signature (§5.2.6, the ts-common shape):
        // without the staged source union this parameter type is unresolvable
        // and exact-signature DI matching used to drop this whole method from
        // the closure — the sink must survive via the name+arity fallback.
        return summarize(query);
    }

    private String summarize(StockQuery query) {
        // Intra-class helper with an unresolved-parameter signature (§5.2.6):
        // the frontend links no call edge for stockSummary -> summarize when
        // StockQuery is off-CPG (the TrainTicket BasicServiceImpl helpers) —
        // self-type name+arity linking must keep this sink reachable.
        Integer stock = restTemplate.getForObject(
                "http://inventory:8081/stock/" + query.getId(), Integer.class);
        return "summary-" + stock;
    }
}
