package com.acme.petstore;

import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Service;
import org.springframework.web.client.RestTemplate;

@Service
public class PetServiceImpl implements PetService {

    private static final String PRIMARY_URL = "http://inventory:8081";
    private static final String AUDIT_URL = "https://audit.example.com";

    @Value("${inventory.url}")
    private String inventoryUrl;

    private final RestTemplate restTemplate;
    private final InventoryClient inventoryClient;
    private final EndpointRegistry endpointRegistry;
    private final ServiceUrlResolver serviceUrlResolver;
    private final boolean preferAudit;

    public PetServiceImpl(
            RestTemplate restTemplate,
            InventoryClient inventoryClient,
            EndpointRegistry endpointRegistry,
            ServiceUrlResolver serviceUrlResolver,
            boolean preferAudit) {
        this.restTemplate = restTemplate;
        this.inventoryClient = inventoryClient;
        this.endpointRegistry = endpointRegistry;
        this.serviceUrlResolver = serviceUrlResolver;
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
        return "pets-of-" + owner;
    }
}
