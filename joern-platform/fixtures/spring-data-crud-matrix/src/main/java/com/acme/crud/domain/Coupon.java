package com.acme.crud.domain;

import jakarta.persistence.Entity;
import jakarta.persistence.Id;
import jakarta.persistence.Table;
import org.hibernate.annotations.SQLDelete;

/** A soft delete: Hibernate runs this update instead of the delete Spring
 *  Data issues, so `deleteById` deletes no row (review B1). */
@Entity
@Table(name = "coupons")
@SQLDelete(sql = "update coupons set deleted = true where id = ?")
public class Coupon {

    @Id
    private Long id;

    private boolean deleted;
}
