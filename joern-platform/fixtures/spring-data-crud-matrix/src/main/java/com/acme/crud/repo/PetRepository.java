package com.acme.crud.repo;

import com.acme.crud.domain.Pet;
import java.util.List;
import org.springframework.data.mongodb.repository.Aggregation;
import org.springframework.data.mongodb.repository.MongoRepository;
import org.springframework.data.mongodb.repository.Query;
import org.springframework.data.mongodb.repository.Update;

public interface PetRepository extends MongoRepository<Pet, String> {

    /** A Mongo query is JSON, not JPQL (R1-24). */
    @Query("{ 'status': ?0 }")
    List<Pet> findByStatusJson(String status);

    /** Spring Data MongoDB's documented `findAndModify` shape: the name reads
     *  like a finder and the method updates every match (review B1). */
    @Update("{ '$inc' : { 'visits' : ?1 } }")
    long findAndIncrementVisitsByStatus(String status, int increment);

    /** An aggregation pipeline: a `$merge` or `$out` stage would write. */
    @Aggregation("{ '$group' : { '_id' : '$status' } }")
    List<String> findStatusSummary();
}
