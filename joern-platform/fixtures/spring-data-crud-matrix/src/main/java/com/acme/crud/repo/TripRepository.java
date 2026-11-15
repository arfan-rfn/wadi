package com.acme.crud.repo;

import com.acme.crud.domain.Trip;
import com.acme.crud.domain.TripId;

public interface TripRepository extends KeyedJpaRepository<TripId, Trip> {
}
