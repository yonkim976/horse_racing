#!/bin/zsh
set -euo pipefail

read -s "database_url?Supabase Session pooler URI를 붙여넣고 Enter: "
printf '\n'

case "$database_url" in
  postgresql://*) database_url="postgresql+psycopg://${database_url#postgresql://}" ;;
  postgres://*) database_url="postgresql+psycopg://${database_url#postgres://}" ;;
  postgresql+psycopg://*) ;;
  *)
    printf '오류: PostgreSQL URI 형식이 아닙니다.\n' >&2
    exit 2
    ;;
esac

case "$database_url" in
  *sslmode=*) ;;
  *\?*) database_url="${database_url}&sslmode=require" ;;
  *) database_url="${database_url}?sslmode=require" ;;
esac

printf '%s' "$database_url" | gcloud secrets versions add \
  horse-racing-database-url \
  --project=mapilog-509017 \
  --data-file=-

unset database_url
printf 'Secret Manager 저장 완료.\n'
