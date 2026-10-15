package com.capstone.order.inventory;

import java.util.Collection;
import java.util.List;
import java.util.Optional;

import org.springframework.data.jpa.repository.JpaRepository;

import org.springframework.data.jpa.repository.Modifying;
import org.springframework.data.jpa.repository.Query;
import org.springframework.data.repository.query.Param;

public interface InventoryRepository extends JpaRepository<Inventory, Long> {

    List<Inventory> findAllByProductIdIn(Collection<Long> productIds);

    Optional<Inventory> findByProductIdAndOptionKey(Long productId, String optionKey);

    @Modifying(flushAutomatically = true, clearAutomatically = true)
    @Query("""
            UPDATE Inventory i
               SET i.quantity = i.quantity - :qty
             WHERE i.productId = :productId
               AND i.optionKey = :optionKey
               AND i.quantity >= :qty
            """)
    int decreaseIfEnough(@Param("productId") Long productId,
                         @Param("optionKey") String optionKey,
                         @Param("qty") int qty);
}

