#!/bin/bash
set -euo pipefail

# Validace vstupů
ACTION=$1      # mount / umount
UNC_PATH=$2    # \\server\share
LOCAL_DIR=$3   # /mnt/server/share

if [[ ! "$LOCAL_DIR" =~ ^/mnt/ ]]; then
    echo "Chyba: Cesta musí začínat na /mnt/" >&2
    exit 1
fi

# Převod zpětných lomítek na dopředná pro Linux cifs helper
SMB_SOURCE=$(echo "$UNC_PATH" | tr "\\" "/")

if [ "$ACTION" = "mount" ]; then
    # Vytvoření adresáře pokud neexistuje
    mkdir -p "$LOCAL_DIR"
    
    # Kontrola, zda již není namountováno
    if mountpoint -q "$LOCAL_DIR"; then
        echo "Již namountováno"
        exit 0
    fi
    
    # Mount s využitím bezpečně uložených přihlašovacích údajů
    # Používáme SMB v3, read-only přístup (RAG asistent data nemění), mapování práv na rag-user
    mount -t cifs "$SMB_SOURCE" "$LOCAL_DIR" \
        -o credentials=/etc/rag/.smbcredentials,ro,nosuid,nodev,noexec,iocharset=utf8,vers=3.0,uid=rag-user,gid=rag-user
        
    echo "Mount úspěšný"

elif [ "$ACTION" = "umount" ]; then
    if mountpoint -q "$LOCAL_DIR"; then
        umount -l "$LOCAL_DIR"
        rmdir "$LOCAL_DIR" || true
        echo "Umount úspěšný"
    else
        echo "Není namountováno"
    fi
fi