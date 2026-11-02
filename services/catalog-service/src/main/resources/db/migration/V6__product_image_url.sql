-- Musinsa's thumbnail address from the product list, loaded by scripts/load_thumbnails.py (ADR-127). Browsers load
-- the image from Musinsa's CDN; no image files are kept. Null when the product was no longer listed at collection.
ALTER TABLE products ADD COLUMN image_url VARCHAR(300);
