package com.acme.crud.domain;

import java.util.List;
import org.springframework.data.annotation.Id;
import org.springframework.data.mongodb.core.mapping.Document;

/** A Mongo document, collection named by the bare `@Document("pets")` form. */
@Document("pets")
public class Pet {

    @Id
    private String id;

    private String status;

    private List<String> tags;

    public Pet() {
    }

    public Pet(String status) {
        this.status = status;
    }

    public String getStatus() {
        return status;
    }
}
