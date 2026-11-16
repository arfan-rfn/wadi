package com.acme.crud.repo;

import jakarta.persistence.EntityManager;
import jakarta.persistence.PersistenceContext;

public class OrderRepositoryImpl implements OrderRepositoryCustom {

    @PersistenceContext
    private EntityManager entityManager;

    @Override
    public int archiveOld() {
        return entityManager
                .createQuery("update Order o set o.status = 'ARCHIVED' where o.status = 'CLOSED'")
                .executeUpdate();
    }
}
