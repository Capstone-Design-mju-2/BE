package com.capstone.order.inventory;

import java.util.Collection;
import java.util.List;

import org.springframework.data.jpa.repository.JpaRepository;

public interface InventoryRepository extends JpaRepository<Inventory, Long> {

    List<Inventory> findAllByProductIdIn(Collection<Long> productIds);
}