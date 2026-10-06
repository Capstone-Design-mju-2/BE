package com.capstone.order.inventory;

import jakarta.persistence.*;

@Entity
@Table(name = "inventory")
public class Inventory {

    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    private Long id;

    @Column(name = "product_id", nullable = false)
    private Long productId;

    @Column(name = "option_key", nullable = false)
    private String optionKey;

    @Column(nullable = false)
    private String name;

    @Column(nullable = false)
    private int price;

    @Column(nullable = false)
    private int quantity;

    protected Inventory() {}

    public Inventory(Long productId, String optionKey, String name, int price, int quantity) {
        this.productId = productId;
        this.optionKey = optionKey;
        this.name = name;
        this.price = price;
        this.quantity = quantity;
    }

    public Long getId() { return id; }
    public Long getProductId() { return productId; }
    public String getOptionKey() { return optionKey; }
    public String getName() { return name; }
    public int getPrice() { return price; }
    public int getQuantity() { return quantity; }

    public void updateNameAndPrice(String name, int price) {
        this.name = name;
        this.price = price;
    }
}