package com.acme.crud.domain;

import org.springframework.data.annotation.Id;
import org.springframework.data.mongodb.core.mapping.Document;

/** Reached through `BaseCrudRepository<PetLog>`, a project base over
 *  MongoRepository whose name contains `CrudRepository` (review A4). */
@Document(collection = "pet_logs")
public class PetLog {

    @Id
    private String id;

    private String entry;
}
