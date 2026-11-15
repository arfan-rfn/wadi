package com.acme.crud.repo;

import com.acme.crud.domain.Shipment;
import org.springframework.data.mongodb.repository.MongoRepository;

public interface ShipmentRepository extends MongoRepository<Shipment, String> {
}
