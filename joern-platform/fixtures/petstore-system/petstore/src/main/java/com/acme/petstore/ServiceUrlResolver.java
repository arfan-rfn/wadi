package com.acme.petstore;

/** The service-registry idiom (as seen in TrainTicket): URLs come from a
 * helper behind a DI interface — resolution needs an interprocedural hop. */
public interface ServiceUrlResolver {
    String getServiceUrl(String serviceName);
}
