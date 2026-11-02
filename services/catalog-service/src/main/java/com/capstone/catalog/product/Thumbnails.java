package com.capstone.catalog.product;

/** Musinsa serves each product image at 125px under the same name with _125 for _500 (ADR-127). */
final class Thumbnails {

    private Thumbnails() {}

    /** About 20KB instead of 195KB. An address of another form comes back unchanged. */
    static String small(String imageUrl) {
        return imageUrl == null ? null : imageUrl.replaceFirst("_500(\\.\\w+)$", "_125$1");
    }
}
