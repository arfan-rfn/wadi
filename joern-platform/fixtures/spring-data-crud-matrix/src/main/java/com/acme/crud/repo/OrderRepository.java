package com.acme.crud.repo;

import com.acme.crud.domain.Order;
import java.util.List;
import jakarta.persistence.LockModeType;
import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.data.jpa.repository.Lock;
import org.springframework.data.jpa.repository.Modifying;
import org.springframework.data.jpa.repository.NativeQuery;
import org.springframework.data.jpa.repository.Query;
import org.springframework.data.jpa.repository.query.Procedure;
import org.springframework.transaction.annotation.Transactional;

public interface OrderRepository extends JpaRepository<Order, String>, OrderRepositoryCustom {

    List<Order> findByStatus(String status);

    long deleteByStatus(String status);

    long countByStatus(String status);

    boolean existsByStatus(String status);

    @Query("select o from Order o where o.status = ?1")
    List<Order> findInStatus(String status);

    @Modifying
    @Query("update Order o set o.status = ?2 where o.id = ?1")
    int updateStatus(String id, String status);

    @Query("select o from Order o join o.lines l where l.sku = ?1")
    List<Order> findContainingSku(String sku);

    @Query(value = "select * from orders where status = ?1", nativeQuery = true)
    List<Order> findNativeByStatus(String status);

    /** The long-query idiom: the text is a concatenation across lines. */
    @Query(value = "select * from orders "
            + "where status = ?1 and id = ?2", nativeQuery = true)
    List<Order> findNativeConcatenated(String status, String id);

    @Query(name = "Order.findShipped")
    List<Order> shipped();

    /** Names a query no entity declares: the text stays unknown (P10). */
    @Query(name = "Order.notDeclaredAnywhere")
    List<Order> undeclaredNamed();

    /** A stored procedure named like a getter: what it does is the
     *  procedure's business, not the name's (review B1). */
    @Procedure(procedureName = "archive_orders")
    int getArchivedCount(String status);

    /** Spring Data JPA 3.4's `@NativeQuery`: a native `@Query` by another name. */
    @NativeQuery("select * from orders where status = ?1")
    List<Order> findNativeAnnotated(String status);

    /** A derived finder under annotations that change how it runs and not
     *  what it does to the entity. */
    @Transactional(readOnly = true)
    @Lock(LockModeType.PESSIMISTIC_WRITE)
    Order findFirstByStatus(String status);

    /** The query comes from a project annotation's own `@Query`. */
    @OpenOrdersQuery
    List<Order> openOrders();

    /** Named like a finder, and it writes: membership of a repository does
     *  not establish what a hand-written body does (C3). */
    default Order findAndTouch(String id) {
        Order order = findById(id).orElseThrow();
        order.setStatus("TOUCHED");
        return save(order);
    }
}
