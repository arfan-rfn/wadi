package com.acme.crud.repo;

import com.acme.crud.domain.Pet;
import java.util.List;
import org.springframework.data.mongodb.repository.MongoRepository;
import org.springframework.data.mongodb.repository.Query;

public interface PetRepository extends MongoRepository<Pet, String> {

    /** A Mongo query is JSON, not JPQL (R1-24). */
    @Query("{ 'status': ?0 }")
    List<Pet> findByStatusJson(String status);
}
