package com.acme.crud.domain;

import org.springframework.data.annotation.Id;
import org.springframework.data.mongodb.core.mapping.Document;

/** A Mongo document, collection named by the `collection =` attribute. No
 *  endpoint reaches it: a declared entity with no detected access (Q6). */
@Document(collection = "shipments")
public class Shipment {

    @Id
    private String id;

    private String carrier;
}
