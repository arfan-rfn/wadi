package com.acme.petstore;

import java.util.HashMap;
import java.util.Map;
import org.springframework.stereotype.Service;

@Service
public class ServiceUrlResolverImpl implements ServiceUrlResolver {

    @Override
    public String getServiceUrl(String serviceName) {
        Map<String, String> serviceMap = new HashMap<>();
        serviceMap.put("inventory-api", "inventory");
        serviceMap.put("billing-api", "billing");
        return "http://" + serviceMap.get(serviceName);
    }
}
