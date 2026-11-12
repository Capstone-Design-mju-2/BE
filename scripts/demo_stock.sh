#!/usr/bin/env bash
# Sets one product's stock for the sold-out demo and puts it back. Run on the demo server from ~/capstone:
#   scripts/demo_stock.sh show 818
#   scripts/demo_stock.sh set 818 1      # the first set keeps the current quantities in ~/demo-stock/818.tsv
#   scripts/demo_stock.sh restore 818    # puts those quantities back and removes the file
# Only inventory quantities change; orders placed meanwhile stay. Locally: COMPOSE=compose.yaml scripts/demo_stock.sh ...
set -euo pipefail

COMPOSE=${COMPOSE:-deploy/compose.yaml}
BACKUP_DIR=${BACKUP_DIR:-$HOME/demo-stock}

die() {
    echo "$*" >&2
    exit 1
}

orders_sql() {
    docker compose -f "$COMPOSE" exec -T order-db \
        psql -U orders -d orders -v ON_ERROR_STOP=1 -At -F $'\t' -c "$1" </dev/null
}

show() {
    orders_sql "SELECT option_key, quantity FROM inventory WHERE product_id = $1 ORDER BY option_key"
}

command=${1:-}
product=${2:-}
[[ $product =~ ^[0-9]+$ ]] || die "usage: $0 show|set|restore <productId> [quantity]"
backup="$BACKUP_DIR/$product.tsv"

case $command in
    show)
        show "$product"
        ;;
    set)
        quantity=${3:-}
        [[ $quantity =~ ^[0-9]+$ ]] || die "usage: $0 set <productId> <quantity>"
        current=$(show "$product")
        [[ -n $current ]] || die "product $product has no inventory"
        mkdir -p "$BACKUP_DIR"
        # Keep the quantities from before the first set, so a second set does not overwrite them.
        [[ -e $backup ]] || printf '%s\n' "$current" > "$backup"
        orders_sql "UPDATE inventory SET quantity = $quantity, version = version + 1 WHERE product_id = $product" > /dev/null
        show "$product"
        ;;
    restore)
        [[ -e $backup ]] || die "no saved quantities for product $product ($backup)"
        updates=""
        while IFS=$'\t' read -r key saved; do
            [[ $saved =~ ^[0-9]+$ ]] || die "bad line in $backup"
            updates+="UPDATE inventory SET quantity = $saved, version = version + 1"
            updates+=" WHERE product_id = $product AND option_key = '${key//\'/\'\'}';"
        done < "$backup"
        orders_sql "$updates" > /dev/null
        rm "$backup"
        show "$product"
        ;;
    *)
        die "usage: $0 show|set|restore <productId> [quantity]"
        ;;
esac
